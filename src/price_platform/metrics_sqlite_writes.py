"""Write-side helpers for metrics SQLite storage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .platform import clock

logger = logging.getLogger(__name__)


class MetricsDBWriteMixin:
    def start_session(self) -> int:
        now = clock.now()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crawl_sessions (started_at, last_heartbeat_at)
                VALUES (?, ?)
                """,
                (now.isoformat(), now.isoformat()),
            )
            conn.commit()
            session_id = cursor.lastrowid
            if session_id is None:
                raise RuntimeError("Failed to get session ID after insert")
            logger.info("Started metrics session %s", session_id)
            return session_id

    def update_heartbeat(self, session_id: int) -> None:
        now = clock.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE crawl_sessions
                SET last_heartbeat_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), session_id),
            )
            conn.commit()

    def update_session_counts(
        self,
        session_id: int,
        *,
        total_items: int,
        success_items: int,
        failed_items: int,
        total_products: int,
        success_products: int,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE crawl_sessions
                SET total_items = ?, success_items = ?, failed_items = ?,
                    total_products = ?, success_products = ?
                WHERE id = ?
                """,
                (total_items, success_items, failed_items, total_products, success_products, session_id),
            )
            conn.commit()

    def increment_round_count(self, session_id: int) -> int:
        current_unique_products = self.get_unique_product_count_for_session(session_id)
        current_total_items = self.get_total_item_count_for_session(session_id)
        now = clock.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE crawl_sessions
                SET round_count = round_count + 1,
                    round_start_product_count = ?,
                    round_start_store_count = ?,
                    last_round_completed_at = ?
                WHERE id = ?
                """,
                (current_unique_products, current_total_items, now.isoformat(), session_id),
            )
            cursor = conn.execute("SELECT round_count FROM crawl_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            conn.commit()
            return row["round_count"] if row else 0

    def mark_work_ended(self, session_id: int) -> None:
        now = clock.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE crawl_sessions
                SET work_ended_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), session_id),
            )
            conn.commit()

    def end_session(self, session_id: int, exit_reason: str = "normal") -> None:
        now = clock.now()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT started_at FROM crawl_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                started_at = datetime.fromisoformat(row["started_at"])
                duration_sec = (now - started_at).total_seconds()
                conn.execute(
                    """
                    UPDATE crawl_sessions
                    SET ended_at = ?, duration_sec = ?, exit_reason = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), duration_sec, exit_reason, session_id),
                )
                conn.commit()
                logger.info("Ended metrics session %s: %s", session_id, exit_reason)

    def close_interrupted_sessions(self) -> int:
        now = clock.now()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, started_at, last_heartbeat_at
                FROM crawl_sessions
                WHERE ended_at IS NULL
                ORDER BY started_at
                """,
            )
            rows = cursor.fetchall()
            closed_count = 0
            for row in rows:
                session_id = row["id"]
                started_at = datetime.fromisoformat(row["started_at"])
                ended_at = datetime.fromisoformat(row["last_heartbeat_at"]) if row["last_heartbeat_at"] else now
                duration_sec = (ended_at - started_at).total_seconds()
                conn.execute(
                    """
                    UPDATE crawl_sessions
                    SET ended_at = ?, duration_sec = ?, exit_reason = ?
                    WHERE id = ?
                    """,
                    (ended_at.isoformat(), duration_sec, "interrupted", session_id),
                )
                closed_count += 1
                logger.warning("Closed interrupted session %s (was started at %s)", session_id, started_at)
            conn.commit()
            return closed_count

    def record_store_stats(
        self,
        session_id: int,
        store_name: str,
        total_items: int,
        success_count: int,
        failed_count: int,
        total_duration_sec: float,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO store_crawl_stats
                    (session_id, store_name, total_items, success_count, failed_count, total_duration_sec)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, store_name) DO UPDATE SET
                    total_items = excluded.total_items,
                    success_count = excluded.success_count,
                    failed_count = excluded.failed_count,
                    total_duration_sec = excluded.total_duration_sec
                """,
                (session_id, store_name, total_items, success_count, failed_count, total_duration_sec),
            )
            conn.commit()

    def record_item_stats(
        self,
        session_id: int,
        store_name: str,
        product_id: str,
        started_at: datetime,
        duration_sec: float | None,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO item_crawl_stats
                    (session_id, store_name, product_id, started_at, duration_sec, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, store_name, product_id, started_at.isoformat(), duration_sec, success, error_message),
            )
            conn.commit()

    def record_amazon_batch(
        self,
        session_id: int,
        started_at: datetime,
        duration_sec: float | None,
        product_count: int,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO amazon_batch_stats
                    (session_id, started_at, duration_sec, product_count, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, started_at.isoformat(), duration_sec, product_count, success, error_message),
            )
            conn.commit()

    def cleanup_old_records(self, days: int = 365) -> int:
        cutoff = clock.now() - timedelta(days=days)
        total_deleted = 0
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM crawl_sessions WHERE started_at < ?", (cutoff.isoformat(),))
            old_session_ids = [row["id"] for row in cursor.fetchall()]
            if old_session_ids:
                placeholders = ",".join("?" * len(old_session_ids))
                for table, column in (
                    ("item_crawl_stats", "session_id"),
                    ("store_crawl_stats", "session_id"),
                    ("amazon_batch_stats", "session_id"),
                    ("crawl_sessions", "id"),
                ):
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",  # noqa: S608
                        old_session_ids,
                    )
                    total_deleted += cursor.rowcount
                conn.commit()
        if total_deleted > 0:
            logger.info("Deleted %d old metrics records", total_deleted)
        return total_deleted
