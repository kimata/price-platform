"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ._metrics_sqlite_models import CrawlSession, LockingMode, StoreCrawlStats
from .metrics_sqlite_analytics import MetricsDBAnalyticsMixin
from .platform import clock
from .sqlite_store import SQLiteStoreBase

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class MetricsDB(MetricsDBAnalyticsMixin, SQLiteStoreBase):
    """SQLite-based metrics data store."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path,
        *,
        locking_mode: LockingMode = "NORMAL",
    ):
        super().__init__(db_path=db_path, schema_path=schema_path, locking_mode=locking_mode)

    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        with self.connection() as conn:
            yield conn

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

    def get_session(self, session_id: int) -> CrawlSession | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM crawl_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return self._row_to_session(row) if row else None

    def get_current_session(self) -> CrawlSession | None:
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

    def get_recent_sessions(self, days: int = 30, limit: int = 100) -> list[CrawlSession]:
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

    def get_store_stats_for_session(self, session_id: int) -> list[StoreCrawlStats]:
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
