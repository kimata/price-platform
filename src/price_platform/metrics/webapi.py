"""メトリクス API エンドポイント（fleama 系アプリ共通実装）。

利用側アプリケーションは MetricsApiSpec でプロジェクト固有の依存
（設定・DB アクセサ・認証デコレータ・カタログ由来の情報）を注入し、
create_metrics_api_blueprint() で Flask Blueprint を生成する。
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import flask
from my_lib.platform import time as platform_time

from price_platform.metrics.client.db import (
    ClientMetricsDB,
    ClientPerfRaw,
    SocialReferralEventRaw,
    WebVitalRaw,
    detect_device_type,
    generate_boxplot_svg,
)
from price_platform.notification.status import build_twitter_status_payload, build_webpush_status_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    from price_platform.metrics.client.db import MetricName, WebVitalName

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricsApiSpec:
    """メトリクス API のプロジェクト固有依存の注入仕様。

    Attributes:
        get_config: アプリ設定を返す callable
        get_metrics_db: クローラーメトリクス DB を返す callable（未設定時 None）
        get_notification_store: 通知ストアを返す callable（未設定時 None）
        get_webpush_store: Web Push ストアを返す callable（未設定時 None）
        get_client_metrics_db: クライアントメトリクス DB を返す callable（未設定時 None）
        require_auth: 認証デコレータ
        total_product_count: カタログ上の製品総数を返す callable
        product_group_resolver: product_id からグループ名（カテゴリ/メーカー等）を解決する callable
        group_stats_key: Web Push ステータスのグループ統計キー（例: "maker_stats"）
        grouped_products_key: Web Push ステータスの製品グループキー
            （例: "product_by_category" / "product_by_maker"）
    """

    get_config: Callable[[], Any]
    get_metrics_db: Callable[[], Any | None]
    get_notification_store: Callable[[], Any | None]
    get_webpush_store: Callable[[], Any | None]
    get_client_metrics_db: Callable[[], Any | None]
    require_auth: Callable[..., Any]
    total_product_count: Callable[[], int]
    product_group_resolver: Callable[[str], str | None]
    group_stats_key: str
    grouped_products_key: str


def create_metrics_api_blueprint(spec: MetricsApiSpec, *, name: str = "metrics") -> flask.Blueprint:
    """MetricsApiSpec からメトリクス API の Blueprint を生成する。"""

    def _get_total_product_count() -> int:
        """カタログ上の製品総数を取得する（利用不可の場合は 0）。"""
        try:
            return spec.total_product_count()
        except (RuntimeError, FileNotFoundError) as e:
            # Expected: カタログ未初期化または設定ファイルなし
            logger.debug("Catalog not available: %s", e)
            return 0
        except (TypeError, AttributeError) as e:
            # Unexpected: スキーマ不一致または内部エラー
            logger.warning("Failed to count products (internal error): %s", e)
            return 0

    get_config = spec.get_config
    require_auth = spec.require_auth

    blueprint = flask.Blueprint(name, __name__)

    def _ensure_metrics_db() -> Any:
        """Ensure metrics DB is initialized and return it."""
        db = spec.get_metrics_db()
        if db is None:
            raise RuntimeError("Metrics DB is not configured")
        return db

    @blueprint.route("/status", methods=["GET"])
    @require_auth
    def get_status() -> tuple[flask.Response, int]:
        """Get current crawl session status."""
        db = _ensure_metrics_db()
        total_product_count = _get_total_product_count()
        status = db.get_session_status(total_product_count=total_product_count)

        cycle_stats_data = None
        if status.cycle_stats:
            cycle_stats_data = {
                "completed_cycles": status.cycle_stats.completed_cycles,
                "cycle_duration_sec": status.cycle_stats.cycle_duration_sec,
                "unique_product_count": status.cycle_stats.unique_product_count,
                "total_product_count": status.cycle_stats.total_product_count,
                "current_cycle_products": status.cycle_stats.current_cycle_products,
                "current_cycle_stores": status.cycle_stats.current_cycle_stores,
                "total_item_count": status.cycle_stats.total_item_count,
                "cumulative_product_count": status.cycle_stats.cumulative_product_count,
            }

        return flask.jsonify(
            {
                "is_running": status.is_running,
                "session_id": status.session_id,
                "started_at": status.started_at.isoformat() if status.started_at else None,
                "last_heartbeat_at": (
                    status.last_heartbeat_at.isoformat() if status.last_heartbeat_at else None
                ),
                # 処理アイテム数（ストア×製品の組み合わせ）
                "processed_items": status.processed_items,
                "success_items": status.success_items,
                "failed_items": status.failed_items,
                # ユニークな製品数
                "processed_products": status.processed_products,
                "success_products": status.success_products,
                "cycle_stats": cycle_stats_data,
            }
        ), 200

    @blueprint.route("/sessions", methods=["GET"])
    @require_auth
    def get_sessions() -> tuple[flask.Response, int]:
        """Get recent crawl sessions."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 30, type=int)
        limit = flask.request.args.get("limit", 100, type=int)

        sessions = db.get_recent_sessions(days=days, limit=limit)
        total_product_count = _get_total_product_count()

        # 最新の「終了していない」セッションを特定
        # sessions は started_at DESC でソートされているので、最初に見つかった is_running が最新
        latest_running_id: int | None = None
        for s in sessions:
            if s.is_running:
                latest_running_id = s.id
                break

        session_data = []
        for s in sessions:
            cycle_stats = (
                db.calculate_cycle_stats(s, total_product_count) if total_product_count > 0 else None
            )

            # 最新の running セッション以外で is_running の場合は、終了済みとして扱う
            is_running = s.is_running and s.id == latest_running_id
            effective_ended_at: str | None
            effective_exit_reason: str | None
            effective_duration_sec: float | None

            if s.is_running and s.id != latest_running_id:
                # 古いセッション（superseded）は last_heartbeat_at で終了したとみなす
                effective_ended_at = s.last_heartbeat_at.isoformat() if s.last_heartbeat_at else None
                effective_exit_reason = "superseded"
                # 稼働時間を推測（last_heartbeat_at - started_at）
                if s.last_heartbeat_at:
                    effective_duration_sec = (s.last_heartbeat_at - s.started_at).total_seconds()
                else:
                    effective_duration_sec = None
            elif is_running:
                # 最新の running セッション: 現在時刻までの経過時間
                now = platform_time.now()
                effective_ended_at = None
                effective_exit_reason = None
                effective_duration_sec = (now - s.started_at).total_seconds()
            elif s.is_timed_out:
                # timeout（heartbeat が古すぎて強制終了扱い）
                effective_ended_at = s.last_heartbeat_at.isoformat() if s.last_heartbeat_at else None
                effective_exit_reason = s.effective_exit_reason  # "timeout"
                # 稼働時間を推測（last_heartbeat_at - started_at）
                if s.last_heartbeat_at:
                    effective_duration_sec = (s.last_heartbeat_at - s.started_at).total_seconds()
                else:
                    effective_duration_sec = None
            else:
                # 正常終了
                effective_ended_at = s.ended_at.isoformat() if s.ended_at else None
                effective_exit_reason = s.effective_exit_reason
                effective_duration_sec = s.duration_sec

            session_data.append(
                {
                    "id": s.id,
                    "started_at": s.started_at.isoformat(),
                    "ended_at": effective_ended_at,
                    "work_ended_at": s.work_ended_at.isoformat() if s.work_ended_at else None,
                    "duration_sec": effective_duration_sec,
                    # 処理アイテム数（ストア×製品の組み合わせ）
                    "total_items": s.total_items,
                    "success_items": s.success_items,
                    "failed_items": s.failed_items,
                    # 処理製品数（累計: 巡回回数を考慮）
                    "total_products": cycle_stats.cumulative_product_count
                    if cycle_stats
                    else s.total_products,
                    "success_products": s.success_products,
                    "exit_reason": effective_exit_reason,
                    "is_running": is_running,
                    "cycle_stats": {
                        "completed_cycles": cycle_stats.completed_cycles,
                        "cycle_duration_sec": cycle_stats.cycle_duration_sec,
                        "unique_product_count": cycle_stats.unique_product_count,
                        "total_product_count": cycle_stats.total_product_count,
                        "current_cycle_products": cycle_stats.current_cycle_products,
                        "current_cycle_stores": cycle_stats.current_cycle_stores,
                        "total_item_count": cycle_stats.total_item_count,
                        "cumulative_product_count": cycle_stats.cumulative_product_count,
                    }
                    if cycle_stats
                    else None,
                }
            )

        return flask.jsonify(
            {
                "sessions": session_data,
                "count": len(sessions),
            }
        ), 200

    @blueprint.route("/sessions/<int:session_id>", methods=["GET"])
    @require_auth
    def get_session_detail(session_id: int) -> tuple[flask.Response, int]:
        """Get detailed information for a specific session."""
        db = _ensure_metrics_db()
        session = db.get_session(session_id)

        if session is None:
            return flask.jsonify({"error": f"Session not found: {session_id}"}), 404

        store_stats = db.get_store_stats_for_session(session_id)
        item_stats = db.get_item_stats_for_session(session_id)

        total_product_count = _get_total_product_count()
        cycle_stats = (
            db.calculate_cycle_stats(session, total_product_count) if total_product_count > 0 else None
        )

        return flask.jsonify(
            {
                "session": {
                    "id": session.id,
                    "started_at": session.started_at.isoformat(),
                    "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                    "work_ended_at": session.work_ended_at.isoformat() if session.work_ended_at else None,
                    "duration_sec": session.duration_sec,
                    # 処理アイテム数（ストア×製品の組み合わせ）
                    "total_items": session.total_items,
                    "success_items": session.success_items,
                    "failed_items": session.failed_items,
                    # 処理製品数（累計: 巡回回数を考慮）
                    "total_products": cycle_stats.cumulative_product_count
                    if cycle_stats
                    else session.total_products,
                    "success_products": session.success_products,
                    "exit_reason": session.effective_exit_reason,
                    "is_running": session.is_running,
                },
                "store_stats": [
                    {
                        "store_name": s.store_name,
                        "total_items": s.total_items,
                        "success_count": s.success_count,
                        "failed_count": s.failed_count,
                        "total_duration_sec": s.total_duration_sec,
                        "avg_duration_sec": s.avg_duration_sec,
                        "success_rate": s.success_rate,
                    }
                    for s in store_stats
                ],
                "item_count": len(item_stats),
            }
        ), 200

    @blueprint.route("/stores", methods=["GET"])
    @require_auth
    def get_store_stats() -> tuple[flask.Response, int]:
        """Get aggregated store statistics."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 30, type=int)

        stats = db.get_store_aggregate_stats(days=days)

        return flask.jsonify(
            {
                "stores": [
                    {
                        "store_name": s.store_name,
                        "total_sessions": s.total_sessions,
                        "total_items": s.total_items,
                        "success_count": s.success_count,
                        "failed_count": s.failed_count,
                        "total_duration_sec": s.total_duration_sec,
                        "avg_duration_sec": s.avg_duration_sec,
                        "success_rate": s.success_rate,
                    }
                    for s in stats
                ],
                "days": days,
            }
        ), 200

    @blueprint.route("/heatmap", methods=["GET"])
    @require_auth
    def get_heatmap() -> tuple[flask.Response, int]:
        """Get heatmap data for crawl activity (30-minute intervals).

        Now uses item_crawl_stats for real-time updates, including running sessions.
        """
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 90, type=int)

        entries = db.get_heatmap_data(days=days)

        return flask.jsonify(
            {
                "entries": [
                    {
                        "date": e.date,
                        "slot": e.slot,
                        "item_count": e.item_count,
                        "success_count": e.success_count,
                        "failed_count": e.failed_count,
                        "total_duration_sec": e.total_duration_sec,
                        "success_rate": e.success_rate,
                    }
                    for e in entries
                ],
                "days": days,
            }
        ), 200

    @blueprint.route("/heatmap.svg", methods=["GET"])
    @require_auth
    def get_heatmap_svg() -> tuple[flask.Response, int]:
        """Generate heatmap as SVG image (GitHub-style, 30-minute intervals)."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 90, type=int)

        entries = db.get_heatmap_data(days=days)

        # Create a dictionary for quick lookup (slot: 0-47 for 30-minute intervals)
        heatmap_dict: dict[tuple[str, int], float] = {}
        for e in entries:
            heatmap_dict[(e.date, e.slot)] = e.success_rate

        # Generate SVG
        svg = _generate_heatmap_svg(heatmap_dict, days)

        response = flask.make_response(svg)
        response.headers["Content-Type"] = "image/svg+xml"
        return response, 200

    def _generate_heatmap_svg(heatmap_dict: dict[tuple[str, int], float], days: int) -> str:
        """Generate GitHub-style heatmap SVG (30-minute intervals)."""
        # Configuration
        cell_size = 8
        cell_gap = 1
        slots = 48  # 30-minute intervals (24 hours * 2)
        weeks = (days + 6) // 7

        # Calculate dimensions
        width = weeks * (cell_size + cell_gap) + 60
        height = slots * (cell_size + cell_gap) + 40

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            "<style>",
            ".cell { stroke: #ccc; stroke-width: 0.5; }",
            ".label { font-family: sans-serif; font-size: 10px; fill: #333; }",
            "</style>",
        ]

        # Add hour labels (every 3 hours)
        for h in range(0, 24, 3):
            slot = h * 2
            y = 30 + slot * (cell_size + cell_gap) + cell_size / 2
            svg_parts.append(f'<text x="5" y="{y}" class="label">{h:02d}</text>')

        # Generate cells
        now = platform_time.now()
        start_date = (now - timedelta(days=days)).date()

        for day_offset in range(days):
            current_date = start_date + timedelta(days=day_offset)
            week = day_offset // 7
            x = 50 + week * (cell_size + cell_gap)

            for slot in range(slots):
                y = 30 + slot * (cell_size + cell_gap)
                date_str = current_date.isoformat()
                success_rate = heatmap_dict.get((date_str, slot), -1)

                if success_rate < 0:
                    fill = "#eee"  # No data
                elif success_rate >= 0.95:
                    fill = "#2da44e"  # High success (green)
                elif success_rate >= 0.8:
                    fill = "#40c463"  # Good success
                elif success_rate >= 0.5:
                    fill = "#ffdf5d"  # Medium (yellow)
                else:
                    fill = "#f85149"  # Low success (red)

                svg_parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                    f'fill="{fill}" class="cell" />'
                )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    @blueprint.route("/crawl-time/boxplot", methods=["GET"])
    @require_auth
    def get_crawl_time_boxplot() -> tuple[flask.Response, int]:
        """Get crawl time boxplot data per store."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 30, type=int)

        stats = db.get_store_aggregate_stats(days=days)
        store_names = [s.store_name for s in stats]

        result: list[dict[str, Any]] = []
        for store_name in store_names:
            durations = db.get_store_durations(store_name, days=days)
            if not durations:
                continue

            # Calculate boxplot statistics
            sorted_durations = sorted(durations)
            n = len(sorted_durations)

            min_val = sorted_durations[0]
            max_val = sorted_durations[-1]
            median = statistics.median(sorted_durations)

            # Quartiles
            q1_idx = n // 4
            q3_idx = (3 * n) // 4
            q1 = sorted_durations[q1_idx] if q1_idx < n else min_val
            q3 = sorted_durations[q3_idx] if q3_idx < n else max_val

            result.append(
                {
                    "store_name": store_name,
                    "min": min_val,
                    "q1": q1,
                    "median": median,
                    "q3": q3,
                    "max": max_val,
                    "count": n,
                    "avg": statistics.mean(durations),
                }
            )

        return flask.jsonify(
            {
                "stores": result,
                "days": days,
            }
        ), 200

    @blueprint.route("/failures/timeseries", methods=["GET"])
    @require_auth
    def get_failure_timeseries() -> tuple[flask.Response, int]:
        """Get failure count timeseries data."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 30, type=int)

        data = db.get_failure_timeseries(days=days)

        # Group by date
        by_date: dict[str, dict[str, int]] = {}
        for row in data:
            date = row.date
            store = row.store_name
            count = row.failure_count
            if date not in by_date:
                by_date[date] = {}
            by_date[date][store] = count

        return flask.jsonify(
            {
                "timeseries": [
                    {"date": date, "failures": stores} for date, stores in sorted(by_date.items())
                ],
                "days": days,
            }
        ), 200

    @blueprint.route("/amazon/batches", methods=["GET"])
    @require_auth
    def get_amazon_batches() -> tuple[flask.Response, int]:
        """Get Amazon API batch statistics."""
        db = _ensure_metrics_db()
        days = flask.request.args.get("days", 30, type=int)

        batches = db.get_amazon_batch_stats(days=days)

        return flask.jsonify(
            {
                "batches": [
                    {
                        "id": b.id,
                        "session_id": b.session_id,
                        "started_at": b.started_at.isoformat(),
                        "duration_sec": b.duration_sec,
                        "product_count": b.product_count,
                        "success": b.success,
                        "error_message": b.error_message,
                    }
                    for b in batches
                ],
                "count": len(batches),
                "days": days,
            }
        ), 200

    # ============================================================================
    # Twitter Metrics Endpoints
    # ============================================================================

    def _get_notification_store() -> Any | None:
        """Get notification store if configured."""
        return spec.get_notification_store()

    @blueprint.route("/twitter", methods=["GET"])
    @require_auth
    def get_twitter_status() -> tuple[flask.Response, int]:
        """Get Twitter posting status."""
        config = get_config()

        if not config.notification or not config.notification.enabled:
            return flask.jsonify({"enabled": False, "message": "Twitter通知は設定されていません"}), 200

        if not config.notification.twitter or not config.notification.twitter.enabled:
            return flask.jsonify({"enabled": False, "message": "Twitter投稿は無効です"}), 200

        store = _get_notification_store()
        if store is None:
            return flask.jsonify({"enabled": False, "message": "通知データベースが見つかりません"}), 200

        try:
            payload = build_twitter_status_payload(store=store, now=platform_time.now())
            return flask.jsonify(payload), 200
        except sqlite3.Error as e:
            logger.exception("Failed to get Twitter status")
            return flask.jsonify({"enabled": True, "error": str(e)}), 200

    def _resolve_product_group(product_id: str) -> str | None:
        """Resolve group name for a product subscription."""
        return spec.product_group_resolver(product_id)

    def _get_webpush_store() -> Any | None:
        """Get webpush store if configured."""
        return spec.get_webpush_store()

    @blueprint.route("/webpush", methods=["GET"])
    @require_auth
    def get_webpush_status() -> tuple[flask.Response, int]:
        """Get Web Push notification status."""
        config = get_config()
        days = flask.request.args.get("days", 30, type=int)

        if not config.notification.webpush or not config.notification.webpush.enabled:
            return flask.jsonify({"enabled": False, "message": "Web Push通知は設定されていません"}), 200

        store = _get_webpush_store()
        if store is None:
            return flask.jsonify({"enabled": False, "message": "Web Pushデータベースが見つかりません"}), 200

        try:
            payload = build_webpush_status_payload(
                store=store,
                now=platform_time.now(),
                days=days,
                product_group_resolver=_resolve_product_group,
                group_stats_key=spec.group_stats_key,
                grouped_products_key=spec.grouped_products_key,
            )
            return flask.jsonify(payload), 200
        except sqlite3.Error as e:
            logger.exception("Failed to get Web Push status")
            return flask.jsonify({"enabled": True, "error": str(e)}), 200

    # ============================================================================
    # Client Performance Metrics Endpoints
    # ============================================================================

    def _ensure_client_metrics_db() -> ClientMetricsDB | None:
        """Ensure client metrics DB is initialized and return it (or None if disabled)."""
        config = get_config()
        if not config.client_metrics.enabled:
            return None

        return spec.get_client_metrics_db()

    @blueprint.route("/client/perf", methods=["POST"])
    def receive_client_perf() -> tuple[flask.Response, int]:
        """Receive client performance data from browser.

        This endpoint does not require authentication to allow sendBeacon from any page.
        """
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"status": "disabled"}), 200

        config = get_config()

        # Sampling check
        import random

        if random.random() > config.client_metrics.sampling_rate:  # noqa: S311
            return flask.jsonify({"status": "sampled_out"}), 200

        # Parse request data
        data = flask.request.get_json(silent=True)
        if data is None:
            return flask.jsonify({"error": "Invalid JSON"}), 400

        # Detect device type from User-Agent header (more reliable than client-side)
        user_agent = flask.request.headers.get("User-Agent")
        device_type = detect_device_type(user_agent)

        # Parse and validate raw data
        data["device_type"] = device_type
        data["user_agent"] = user_agent
        raw_data = ClientPerfRaw.parse(data)
        if raw_data is None:
            return flask.jsonify({"error": "Invalid performance data"}), 400

        # Save to database
        try:
            db.save_raw(raw_data)
            return flask.jsonify({"status": "ok"}), 200
        except sqlite3.Error as e:
            logger.warning(f"Failed to save client perf data: {e}")
            return flask.jsonify({"error": "Failed to save"}), 500

    @blueprint.route("/client/web-vitals", methods=["POST"])
    def receive_web_vitals() -> tuple[flask.Response, int]:
        """Receive Core Web Vitals data from browser.

        This endpoint does not require authentication to allow sendBeacon from any page.
        Metrics: LCP, CLS, INP, FCP, TTFB
        """
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"status": "disabled"}), 200

        config = get_config()

        # Sampling check
        import random

        if random.random() > config.client_metrics.sampling_rate:  # noqa: S311
            return flask.jsonify({"status": "sampled_out"}), 200

        # Parse request data
        data = flask.request.get_json(silent=True)
        if data is None:
            return flask.jsonify({"error": "Invalid JSON"}), 400

        # Detect device type from User-Agent
        user_agent = flask.request.headers.get("User-Agent")
        device_type = detect_device_type(user_agent)

        # Parse and validate web vital data
        raw_data = WebVitalRaw.parse(data, device_type)
        if raw_data is None:
            return flask.jsonify({"error": "Invalid web vital data"}), 400

        logger.debug(
            "Web Vital received: %s = %.2f (%s) on %s [%s]",
            raw_data.metric_name,
            raw_data.metric_value,
            raw_data.rating,
            raw_data.page_path,
            device_type,
        )

        # Save to database
        try:
            db.save_web_vital(raw_data)
            return flask.jsonify({"status": "ok"}), 200
        except sqlite3.Error as e:
            logger.warning(f"Failed to save web vital data: {e}")
            return flask.jsonify({"error": "Failed to save"}), 500

    @blueprint.route("/client/social-referral", methods=["POST"])
    def receive_social_referral() -> tuple[flask.Response, int]:
        """Receive social referral retention events from browser."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"status": "disabled"}), 200

        data = flask.request.get_json(silent=True)
        if data is None:
            return flask.jsonify({"error": "Invalid JSON"}), 400

        user_agent = flask.request.headers.get("User-Agent")
        device_type = detect_device_type(user_agent)
        raw_data = SocialReferralEventRaw.parse(data, device_type, user_agent)
        if raw_data is None:
            return flask.jsonify({"error": "Invalid social referral data"}), 400

        try:
            db.save_social_referral_event(raw_data)
            return flask.jsonify({"status": "ok"}), 200
        except sqlite3.Error as e:
            logger.warning(f"Failed to save social referral data: {e}")
            return flask.jsonify({"error": "Failed to save"}), 500

    @blueprint.route("/client/social-referral/summary", methods=["GET"])
    @require_auth
    def get_social_referral_summary() -> tuple[flask.Response, int]:
        """Get aggregated social referral retention events."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"error": "Client metrics disabled"}), 404

        days = flask.request.args.get("days", 30, type=int)
        return flask.jsonify(db.get_social_referral_summary(days=days).to_dict()), 200

    @blueprint.route("/client/daily", methods=["GET"])
    @require_auth
    def get_client_perf_daily() -> tuple[flask.Response, int]:
        """Get daily aggregated client performance data."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"error": "Client metrics disabled"}), 404

        days = flask.request.args.get("days", 30, type=int)
        metric: MetricName = flask.request.args.get("metric", "load_event_ms")  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        # Validate metric name
        valid_metrics = ["ttfb_ms", "dom_interactive_ms", "dom_complete_ms", "load_event_ms"]
        if metric not in valid_metrics:
            return flask.jsonify({"error": f"Invalid metric. Valid: {valid_metrics}"}), 400

        # Get aggregated data
        data = db.get_daily_boxplot_data(metric, days=days)

        # Get today's realtime stats
        today_stats = db.get_today_realtime_stats(metric)

        return flask.jsonify(
            {
                "data": [
                    {
                        "date": d.date,
                        "device_type": d.device_type,
                        "min": d.min_val,
                        "q1": d.q1,
                        "median": d.median,
                        "q3": d.q3,
                        "max": d.max_val,
                        "avg": d.avg,
                        "count": d.count,
                    }
                    for d in data
                ],
                "today": {
                    device_type: {
                        "min": stats.min_val,
                        "q1": stats.q1,
                        "median": stats.median,
                        "q3": stats.q3,
                        "max": stats.max_val,
                        "avg": stats.avg,
                        "count": stats.count,
                    }
                    if stats
                    else None
                    for device_type, stats in today_stats.items()
                },
                "metric": metric,
                "days": days,
            }
        ), 200

    @blueprint.route("/client/boxplot.svg", methods=["GET"])
    @require_auth
    def get_client_perf_boxplot_svg() -> tuple[flask.Response, int]:
        """Generate client performance boxplot as SVG."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"error": "Client metrics disabled"}), 404

        days = flask.request.args.get("days", 30, type=int)
        metric: MetricName = flask.request.args.get("metric", "load_event_ms")  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        # Validate metric name
        valid_metrics = ["ttfb_ms", "dom_interactive_ms", "dom_complete_ms", "load_event_ms"]
        if metric not in valid_metrics:
            return flask.jsonify({"error": f"Invalid metric. Valid: {valid_metrics}"}), 400

        # Get data (includes today and yesterday from raw data if not aggregated)
        data = db.get_daily_boxplot_data(metric, days=days)

        # Generate title
        metric_labels = {
            "ttfb_ms": "初回バイト受信時間 (TTFB)",
            "dom_interactive_ms": "DOM 対話可能時間",
            "dom_complete_ms": "DOM 完了時間",
            "load_event_ms": "ページ読み込み時間",
        }
        title = f"{metric_labels.get(metric, metric)} (ms) - 過去{days}日"

        # Generate SVG (convert list to tuple for caching)
        svg = generate_boxplot_svg(tuple(data), title)

        response = flask.make_response(svg)
        response.headers["Content-Type"] = "image/svg+xml"
        return response, 200

    # -------------------------------------------------------------------------
    # Core Web Vitals endpoints
    # -------------------------------------------------------------------------

    @blueprint.route("/client/web-vitals/summary", methods=["GET"])
    @require_auth
    def get_web_vitals_summary() -> tuple[flask.Response, int]:
        """Get summary of Core Web Vitals for the last N days."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"error": "Client metrics disabled"}), 404

        days = flask.request.args.get("days", 7, type=int)
        summary = db.get_web_vitals_summary(days=days)

        # Add threshold information for each metric
        thresholds = {
            "LCP": {"good": 2500, "poor": 4000, "unit": "ms"},
            "CLS": {"good": 0.1, "poor": 0.25, "unit": ""},
            "INP": {"good": 200, "poor": 500, "unit": "ms"},
            "FCP": {"good": 1800, "poor": 3000, "unit": "ms"},
            "TTFB": {"good": 800, "poor": 1800, "unit": "ms"},
        }

        return flask.jsonify(
            {
                "days": days,
                "metrics": summary,
                "thresholds": thresholds,
            }
        ), 200

    @blueprint.route("/client/web-vitals/daily", methods=["GET"])
    @require_auth
    def get_web_vitals_daily() -> tuple[flask.Response, int]:
        """Get daily Core Web Vitals data for a specific metric."""
        db = _ensure_client_metrics_db()
        if db is None:
            return flask.jsonify({"error": "Client metrics disabled"}), 404

        days = flask.request.args.get("days", 30, type=int)
        metric: WebVitalName = flask.request.args.get("metric", "LCP")  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        # Validate metric name
        valid_metrics = ["LCP", "CLS", "INP", "FCP", "TTFB"]
        if metric not in valid_metrics:
            return flask.jsonify({"error": f"Invalid metric. Valid: {valid_metrics}"}), 400

        data = db.get_web_vitals_daily(metric, days=days)

        return flask.jsonify(
            {
                "metric": metric,
                "days": days,
                "data": [
                    {
                        "date": d.date,
                        "device_type": d.device_type,
                        "min": d.min_val,
                        "q1": d.q1,
                        "median": d.median,
                        "q3": d.q3,
                        "max": d.max_val,
                        "avg": d.avg,
                        "count": d.count,
                        "good_pct": d.good_pct,
                        "needs_improvement_pct": d.needs_improvement_pct,
                        "poor_pct": d.poor_pct,
                    }
                    for d in data
                ],
            }
        ), 200

    return blueprint
