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
        logging.warning("メトリクス DB が見つかりません: %s（セッションチェックをスキップ）", metrics_db_path)
        return True

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


def check_web_servers(_config: Any, definition: HealthzCliDefinition) -> bool:
    """Run web server health checks."""
    failed = my_lib.healthz.check_healthz_all(
        http_targets=[
            my_lib.healthz.HttpHealthzTarget(name="flask-api", url=definition.api_healthz_url),
            my_lib.healthz.HttpHealthzTarget(name="node-ssr", url="http://localhost:3000/healthz"),
        ]
    )
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
    if "web" in targets and not check_web_servers(config, definition):
        all_ok = False

    if all_ok:
        logging.info("OK.")
        sys.exit(0)

    logging.error("NG.")
    sys.exit(1)
