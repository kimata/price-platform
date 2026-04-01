"""Read-side helpers for metrics SQLite storage."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ._metrics_sqlite_models import (
    AmazonBatchStats,
    CrawlSession,
    CycleStats,
    HeatmapEntry,
    ItemCrawlStats,
    SessionStatus,
    StoreAggregateStats,
    StoreCrawlStats,
)
from ._sqlite_protocols import MetricsRowMapper
from .platform import clock

logger = logging.getLogger(__name__)


class MetricsDBReadMixin:
    def get_session(self: MetricsRowMapper, session_id: int) -> CrawlSession | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM crawl_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return self._row_to_session(row) if row else None

    def get_current_session(self: MetricsRowMapper) -> CrawlSession | None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM crawl_sessions
                WHERE ended_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
            )
            row = cursor.fetchone()
            return self._row_to_session(row) if row else None

    def get_recent_sessions(self: MetricsRowMapper, days: int = 30, limit: int = 100) -> list[CrawlSession]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM crawl_sessions
                WHERE started_at >= ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (since.isoformat(), limit),
            )
            return [self._row_to_session(row) for row in cursor.fetchall()]

    def get_store_stats_for_session(self: MetricsRowMapper, session_id: int) -> list[StoreCrawlStats]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT store_name, total_items, success_count, failed_count, total_duration_sec
                FROM store_crawl_stats
                WHERE session_id = ?
                """,
                (session_id,),
            )
            return [
                StoreCrawlStats(
                    store_name=row["store_name"],
                    total_items=row["total_items"],
                    success_count=row["success_count"],
                    failed_count=row["failed_count"],
                    total_duration_sec=row["total_duration_sec"],
                )
                for row in cursor.fetchall()
            ]

    def get_store_aggregate_stats(self: MetricsRowMapper, days: int = 30) -> list[StoreAggregateStats]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    store_name,
                    COUNT(DISTINCT session_id) as total_sessions,
                    COUNT(*) as total_items,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_count,
                    COALESCE(SUM(duration_sec), 0) as total_duration_sec
                FROM item_crawl_stats
                WHERE started_at >= ?
                GROUP BY store_name
                """,
                (since.isoformat(),),
            )
            results = []
            for row in cursor.fetchall():
                total_items = row["total_items"] or 0
                success_count = row["success_count"] or 0
                failed_count = row["failed_count"] or 0
                total_duration_sec = row["total_duration_sec"] or 0.0
                results.append(
                    StoreAggregateStats(
                        store_name=row["store_name"],
                        total_sessions=row["total_sessions"],
                        total_items=total_items,
                        success_count=success_count,
                        failed_count=failed_count,
                        total_duration_sec=total_duration_sec,
                        avg_duration_sec=total_duration_sec / success_count if success_count > 0 else 0.0,
                        success_rate=success_count / total_items if total_items > 0 else 0.0,
                    )
                )
            return results

    def get_item_stats_for_session(self: MetricsRowMapper, session_id: int) -> list[ItemCrawlStats]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM item_crawl_stats
                WHERE session_id = ?
                ORDER BY started_at
                """,
                (session_id,),
            )
            return [self._row_to_item_stats(row) for row in cursor.fetchall()]

    def get_store_durations(self: MetricsRowMapper, store_name: str, days: int = 30, limit: int = 1000) -> list[float]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT i.duration_sec
                FROM item_crawl_stats i
                JOIN crawl_sessions c ON i.session_id = c.id
                WHERE i.store_name = ?
                  AND i.success = TRUE
                  AND i.duration_sec IS NOT NULL
                  AND c.started_at >= ?
                ORDER BY i.started_at DESC
                LIMIT ?
                """,
                (store_name, since.isoformat(), limit),
            )
            return [row["duration_sec"] for row in cursor.fetchall()]

    def get_amazon_batch_stats(self: MetricsRowMapper, days: int = 30) -> list[AmazonBatchStats]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM amazon_batch_stats
                WHERE started_at >= ?
                ORDER BY started_at DESC
                """,
                (since.isoformat(),),
            )
            return [self._row_to_amazon_batch(row) for row in cursor.fetchall()]

    def get_heatmap_data(self: MetricsRowMapper, days: int = 90) -> list[HeatmapEntry]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    DATE(SUBSTR(started_at, 1, 19)) as date,
                    CAST(strftime('%H', SUBSTR(started_at, 1, 19)) AS INTEGER) * 2 +
                        CASE WHEN CAST(strftime('%M', SUBSTR(started_at, 1, 19)) AS INTEGER) >= 30
                        THEN 1 ELSE 0 END as slot,
                    COUNT(*) as item_count,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_count,
                    COALESCE(SUM(duration_sec), 0) as total_duration_sec
                FROM item_crawl_stats
                WHERE started_at >= ?
                GROUP BY DATE(SUBSTR(started_at, 1, 19)), slot
                ORDER BY date, slot
                """,
                (since.isoformat(),),
            )
            return [
                HeatmapEntry(
                    date=row["date"],
                    slot=row["slot"],
                    item_count=row["item_count"],
                    success_count=row["success_count"],
                    failed_count=row["failed_count"],
                    total_duration_sec=row["total_duration_sec"],
                )
                for row in cursor.fetchall()
            ]

    def get_failure_timeseries(self: MetricsRowMapper, days: int = 30) -> list[dict]:
        since = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    DATE(SUBSTR(c.started_at, 1, 19)) as date,
                    i.store_name,
                    COUNT(*) as failure_count
                FROM item_crawl_stats i
                JOIN crawl_sessions c ON i.session_id = c.id
                WHERE i.success = FALSE AND c.started_at >= ?
                GROUP BY DATE(SUBSTR(c.started_at, 1, 19)), i.store_name
                ORDER BY date
                """,
                (since.isoformat(),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_unique_product_count_for_session(self: MetricsRowMapper, session_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(DISTINCT product_id) as unique_product_count
                FROM item_crawl_stats
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            return row["unique_product_count"] if row else 0

    def get_total_item_count_for_session(self: MetricsRowMapper, session_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM item_crawl_stats WHERE session_id = ?", (session_id,))
            item_count = cursor.fetchone()["cnt"]
            cursor = conn.execute(
                "SELECT COALESCE(SUM(product_count), 0) as cnt FROM amazon_batch_stats WHERE session_id = ?",
                (session_id,),
            )
            amazon_count = cursor.fetchone()["cnt"]
            return item_count + amazon_count

    def calculate_cycle_stats(self: MetricsRowMapper, session: CrawlSession, total_product_count: int) -> CycleStats:
        unique_product_count = self.get_unique_product_count_for_session(session.id)
        total_item_count = self.get_total_item_count_for_session(session.id)
        completed_cycles = session.round_count
        current_cycle_stores = total_item_count - session.round_start_store_count
        if completed_cycles == 0:
            current_cycle_products = unique_product_count - session.round_start_product_count
        elif current_cycle_stores > 0 and unique_product_count > 0:
            avg_stores_per_product = total_item_count / unique_product_count if unique_product_count > 0 else 1
            current_cycle_products = min(total_product_count, int(current_cycle_stores / avg_stores_per_product))
        else:
            current_cycle_products = 0

        cycle_duration_sec: float | None = None
        if completed_cycles > 0:
            if session.work_ended_at:
                work_duration = (session.work_ended_at - session.started_at).total_seconds()
            elif session.ended_at:
                work_duration = (session.ended_at - session.started_at).total_seconds()
            elif session.last_round_completed_at:
                work_duration = (session.last_round_completed_at - session.started_at).total_seconds()
            else:
                work_duration = (clock.now() - session.started_at).total_seconds()
            cycle_duration_sec = work_duration / completed_cycles

        return CycleStats(
            completed_cycles=completed_cycles,
            cycle_duration_sec=cycle_duration_sec,
            unique_product_count=unique_product_count,
            total_product_count=total_product_count,
            current_cycle_products=current_cycle_products,
            current_cycle_stores=current_cycle_stores,
            total_item_count=total_item_count,
            cumulative_product_count=unique_product_count * completed_cycles + current_cycle_products,
        )

    def get_session_status(self, total_product_count: int = 0) -> SessionStatus:
        session = self.get_current_session()
        if session:
            cycle_stats = self.calculate_cycle_stats(session, total_product_count)
            return SessionStatus(
                is_running=True,
                session_id=session.id,
                started_at=session.started_at,
                last_heartbeat_at=session.last_heartbeat_at,
                processed_items=cycle_stats.total_item_count,
                success_items=session.success_items,
                failed_items=session.failed_items,
                processed_products=cycle_stats.cumulative_product_count,
                success_products=session.success_products,
                cycle_stats=cycle_stats,
            )
        return SessionStatus(is_running=False)

    def is_crawler_healthy(self, max_age_sec: float = 600) -> bool:
        session = self.get_current_session()
        if session is None:
            logger.warning("No active session found")
            return False
        if session.last_heartbeat_at is None:
            logger.warning("Session has no heartbeat")
            return False
        elapsed = (clock.now() - session.last_heartbeat_at).total_seconds()
        if elapsed > max_age_sec:
            logger.warning("Heartbeat too old: %.1fs (max: %ss)", elapsed, max_age_sec)
            return False
        return True

    def _row_to_session(self, row: sqlite3.Row) -> CrawlSession:
        row_dict: dict[str, Any] = dict(row)
        return CrawlSession(
            id=row_dict["id"],
            started_at=datetime.fromisoformat(row_dict["started_at"]),
            last_heartbeat_at=(
                datetime.fromisoformat(row_dict["last_heartbeat_at"]) if row_dict["last_heartbeat_at"] else None
            ),
            ended_at=(datetime.fromisoformat(row_dict["ended_at"]) if row_dict["ended_at"] else None),
            work_ended_at=(
                datetime.fromisoformat(row_dict["work_ended_at"]) if row_dict["work_ended_at"] else None
            ),
            duration_sec=row_dict["duration_sec"],
            total_items=row_dict["total_items"],
            success_items=row_dict["success_items"],
            failed_items=row_dict["failed_items"],
            total_products=row_dict["total_products"],
            success_products=row_dict["success_products"],
            round_count=row_dict.get("round_count", 0),
            round_start_product_count=row_dict.get("round_start_product_count", 0),
            round_start_store_count=row_dict.get("round_start_store_count", 0),
            last_round_completed_at=(
                datetime.fromisoformat(row_dict["last_round_completed_at"])
                if row_dict.get("last_round_completed_at")
                else None
            ),
            exit_reason=row_dict["exit_reason"],
        )

    def _row_to_item_stats(self, row: sqlite3.Row) -> ItemCrawlStats:
        r: dict[str, Any] = dict(row)
        return ItemCrawlStats(
            id=r["id"],
            session_id=r["session_id"],
            store_name=r["store_name"],
            product_id=r["product_id"],
            started_at=datetime.fromisoformat(r["started_at"]),
            duration_sec=r["duration_sec"],
            success=bool(r["success"]),
            error_message=r["error_message"],
        )

    def _row_to_amazon_batch(self, row: sqlite3.Row) -> AmazonBatchStats:
        r: dict[str, Any] = dict(row)
        return AmazonBatchStats(
            id=r["id"],
            session_id=r["session_id"],
            started_at=datetime.fromisoformat(r["started_at"]),
            duration_sec=r["duration_sec"],
            product_count=r["product_count"],
            success=bool(r["success"]),
            error_message=r["error_message"],
        )
