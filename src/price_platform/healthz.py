"""Shared healthz CLI helpers for price-platform consumer apps."""

from __future__ import annotations

import logging
import pathlib
import sys
from dataclasses import dataclass
from typing import Any, Protocol

import docopt
import my_lib.healthz
import my_lib.logger
from my_lib.platform import time as platform_time


class MetricsDbProtocol(Protocol):
    def is_crawler_healthy(self, *, max_age_sec: int) -> bool: ...
    def get_session_status(self, *, total_product_count: int) -> Any: ...


@dataclass(frozen=True)
class HealthzCliDefinition:
    program_name: str
    logger_name: str
    api_healthz_url: str
    product_label: str
    config_loader: Any
    metrics_db_factory: Any
    total_product_count_getter: Any
    # SSR サーバーの healthz URL。None なら SSR チェックをスキップする。
    # 固定 URL だと SSR を持たない・別ポートのアプリで常に障害と誤判定になる (B13)。
    ssr_healthz_url: str | None = "http://localhost:3000/healthz"
    # メトリクス DB が存在しない状態を正常扱いするか。
    # デフォルトでは異常 (設定ミスで DB が永遠に作られないケースを検出するため)。
    allow_missing_metrics_db: bool = False
    # 価格イベント検出の自己監視 (F1)。config を受け取りイベントストアを返す factory。
    # None ならチェックをスキップ。
    price_event_store_factory: Any = None
    # 検出数を確認する窓 (日)。
    detection_check_days: int = 7
    # 種別ごとのゼロ検出を警告する対象 (イベント種別の value 文字列)。
    detection_expected_event_types: tuple[str, ...] = ()


def check_crawler(config: Any, definition: HealthzCliDefinition) -> bool:
    """Run crawler liveness and session-health checks."""
    liveness_file = config.liveness.file.crawler
    liveness_interval = config.liveness.interval_sec

    failed = my_lib.healthz.check_liveness_all(
        [
            my_lib.healthz.HealthzTarget(
                name="crawler",
                liveness_file=liveness_file,
                interval=liveness_interval,
            ),
        ]
    )
    if failed:
        logging.error("クローラーの liveness チェックに失敗しました: %s", ", ".join(failed))
        return False

    metrics_db_path = config.get_absolute_path(config.metrics.db_path)
    if not metrics_db_path.exists():
        if definition.allow_missing_metrics_db:
            logging.warning(
                "メトリクス DB が見つかりません: %s（セッションチェックをスキップ）", metrics_db_path
            )
            return True
        # クローラーの liveness が正常なのに DB が無いのは設定ミスの兆候。
        # warning + 正常扱いにすると永久に検出できない (B13)。
        logging.error("メトリクス DB が見つかりません: %s", metrics_db_path)
        return False

    metrics_db = definition.metrics_db_factory(metrics_db_path)
    max_age_sec = liveness_interval * 2
    if not metrics_db.is_crawler_healthy(max_age_sec=max_age_sec):
        logging.error(
            "クローラーセッションが異常です（ハートビートが古すぎるか、アクティブなセッションがありません）"
        )
        return False

    total_product_count = definition.total_product_count_getter()
    status = metrics_db.get_session_status(total_product_count=total_product_count)
    if status.is_running and status.started_at is not None:
        now = platform_time.now()
        uptime_sec = (now - status.started_at).total_seconds()
        hours = int(uptime_sec // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        logging.info(
            "クローラー稼働中: session=%d, uptime=%dh%dm, items=%d (success=%d, failed=%d), %s=%d",
            status.session_id or 0,
            hours,
            minutes,
            status.processed_items,
            status.success_items,
            status.failed_items,
            definition.product_label,
            status.processed_products,
        )

    return True


def check_detection_activity(config: Any, definition: HealthzCliDefinition) -> bool:
    """価格イベント検出の自己監視 (F1)。

    「PRICE_DROP が 1 件も出ない」状態 (B1) が誰にも気付かれず続くことを防ぐ。
    直近 N 日で全イベント種別の検出が 0 件なら異常、
    期待種別のゼロ検出は警告としてログに残す。
    """
    if definition.price_event_store_factory is None:
        return True

    event_store = definition.price_event_store_factory(config)
    counts = event_store.get_event_counts_by_type(days=definition.detection_check_days)
    total = sum(counts.values())

    for event_type in definition.detection_expected_event_types:
        if counts.get(event_type, 0) == 0:
            logging.warning(
                "直近 %d 日でイベント種別 %s の検出が 0 件です",
                definition.detection_check_days,
                event_type,
            )

    if total == 0:
        logging.error(
            "直近 %d 日で価格イベントの検出が 1 件もありません（検出パイプラインの停止を疑ってください）",
            definition.detection_check_days,
        )
        return False

    logging.info(
        "価格イベント検出: 直近 %d 日で %d 件 (%s)",
        definition.detection_check_days,
        total,
        ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "なし",
    )
    return True


def check_web_servers(_config: Any, definition: HealthzCliDefinition) -> bool:
    """Run web server health checks."""
    http_targets = [
        my_lib.healthz.HttpHealthzTarget(name="flask-api", url=definition.api_healthz_url),
    ]
    if definition.ssr_healthz_url is not None:
        http_targets.append(
            my_lib.healthz.HttpHealthzTarget(name="node-ssr", url=definition.ssr_healthz_url)
        )
    failed = my_lib.healthz.check_healthz_all(http_targets=http_targets)
    if failed:
        logging.error("Web サーバーのヘルスチェックに失敗しました: %s", ", ".join(failed))
        return False

    logging.info("Web サーバー: 正常")
    return True


def run_healthz_cli(definition: HealthzCliDefinition, doc: str) -> None:
    """Run a standard healthz CLI using the provided definition."""
    args = docopt.docopt(doc)
    config_file = pathlib.Path(args["-c"])
    debug_mode = args["-D"]

    my_lib.logger.init(definition.logger_name, level=logging.DEBUG if debug_mode else logging.INFO)
    logging.info("設定ファイル: %s", config_file)

    config = definition.config_loader(config_file)
    targets: tuple[str, ...]
    if args["--web"]:
        targets = ("web",)
    elif args["--crawler"]:
        targets = ("crawler",)
    else:
        targets = ("crawler", "web")

    all_ok = True
    if "crawler" in targets and not check_crawler(config, definition):
        all_ok = False
    if "crawler" in targets and not check_detection_activity(config, definition):
        all_ok = False
    if "web" in targets and not check_web_servers(config, definition):
        all_ok = False

    if all_ok:
        logging.info("OK.")
        sys.exit(0)

    logging.error("NG.")
    sys.exit(1)
