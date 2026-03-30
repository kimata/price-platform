"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import my_lib.sqlite_util
import my_lib.time

# SQLite ロックモード型
LockingMode = Literal["NORMAL", "EXCLUSIVE"]

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


HEARTBEAT_TIMEOUT_SEC = 600  # 10分


@dataclass(frozen=True)
class CrawlSession:
    """Crawl session data."""

    id: int
    started_at: datetime
    last_heartbeat_at: datetime | None
    ended_at: datetime | None
    work_ended_at: datetime | None
    duration_sec: float | None
    # 処理アイテム数（ストア×製品の組み合わせ）
    total_items: int
    success_items: int
    failed_items: int
    # ユニークな製品数
    total_products: int
    success_products: int
    # 巡回回数
    round_count: int
    # 現在巡回開始時の累計（今回処理数計算用）
    round_start_product_count: int
    round_start_store_count: int
    # 最後の巡回完了時刻（1巡回あたりの時間計算用）
    last_round_completed_at: datetime | None
    exit_reason: str | None

    @property
    def is_running(self) -> bool:
        """Check if session is still running (not ended and heartbeat is recent)."""
        if self.ended_at is not None:
            return False
        # ended_at が None でも heartbeat が古い場合は稼働中とみなさない
        return not self.is_timed_out

    @property
    def is_timed_out(self) -> bool:
        """Check if session has timed out (heartbeat too old)."""
        if self.ended_at is not None:
            return False
        if self.last_heartbeat_at is None:
            return True
        elapsed = (my_lib.time.now() - self.last_heartbeat_at).total_seconds()
        return elapsed > HEARTBEAT_TIMEOUT_SEC

    @property
    def effective_exit_reason(self) -> str | None:
        """Get the exit reason, including timeout detection."""
        if self.exit_reason is not None:
            return self.exit_reason
        if self.is_timed_out:
            return "timeout"
        return None


@dataclass(frozen=True)
class StoreCrawlStats:
    """Store-level crawl statistics."""

    store_name: str
    total_items: int
    success_count: int
    failed_count: int
    total_duration_sec: float

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0-1.0)."""
        if self.total_items == 0:
            return 0.0
        return self.success_count / self.total_items

    @property
    def avg_duration_sec(self) -> float:
        """Calculate average duration per item."""
        if self.success_count == 0:
            return 0.0
        return self.total_duration_sec / self.success_count


@dataclass(frozen=True)
class ItemCrawlStats:
    """Item-level crawl statistics."""

    id: int
    session_id: int
    store_name: str
    product_id: str
    started_at: datetime
    duration_sec: float | None
    success: bool
    error_message: str | None


@dataclass(frozen=True)
class AmazonBatchStats:
    """Amazon API batch statistics."""

    id: int
    session_id: int
    started_at: datetime
    duration_sec: float | None
    product_count: int
    success: bool
    error_message: str | None


@dataclass
class CycleStats:
    """Statistics for product catalog cycles within a session."""

    completed_cycles: int  # 完了した巡回回数
    cycle_duration_sec: float | None  # 1巡回あたりの時間（秒）
    unique_product_count: int  # 処理したユニーク製品数
    total_product_count: int  # 全製品数
    current_cycle_products: int = 0  # 今回処理製品数
    current_cycle_stores: int = 0  # 今回処理ストア数
    total_item_count: int = 0  # 累計処理ストア数（リアルタイム）
    cumulative_product_count: int = 0  # 累計処理製品数（延べ）


@dataclass
class SessionStatus:
    """Current session status for API response."""

    is_running: bool
    session_id: int | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    # 処理アイテム数（ストア×製品の組み合わせ）
    processed_items: int = 0
    success_items: int = 0
    failed_items: int = 0
    # ユニークな製品数
    processed_products: int = 0
    success_products: int = 0
    cycle_stats: CycleStats | None = None


@dataclass
class HeatmapEntry:
    """Heatmap entry for a single time slot (30-minute intervals).

    Uses item_crawl_stats for real-time updates, including running sessions.
    """

    date: str
    slot: int  # 0-47 (30-minute intervals: 0 = 00:00-00:30, 1 = 00:30-01:00, ...)
    item_count: int  # Number of items processed in this slot
    success_count: int  # Number of successful items
    failed_count: int  # Number of failed items
    total_duration_sec: float

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0-1.0)."""
        if self.item_count == 0:
            return 0.0
        return self.success_count / self.item_count


@dataclass
class StoreAggregateStats:
    """Aggregated statistics for a store across all sessions."""

    store_name: str
    total_sessions: int
    total_items: int
    success_count: int
    failed_count: int
    total_duration_sec: float
    avg_duration_sec: float
    success_rate: float
    durations: list[float] = field(default_factory=list)


class MetricsDB:
    """SQLite-based metrics data store."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path,
        *,
        locking_mode: LockingMode = "NORMAL",
    ):
        """Initialize metrics store.

        Args:
            db_path: Path to the database file
            schema_path: Path to the schema file
            locking_mode: SQLite locking mode (NORMAL for concurrent read, EXCLUSIVE for single process)
        """
        self._db_path = db_path
        self._schema_path = schema_path
        self._locking_mode: LockingMode = locking_mode
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Ensure database and tables exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self._schema_path}")

        my_lib.sqlite_util.init_schema_from_file(
            self._db_path, self._schema_path, locking_mode=self._locking_mode
        )

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection with WAL mode and optimized settings."""
        with my_lib.sqlite_util.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    # Session management
    def start_session(self) -> int:
        """Start a new crawl session. Returns session ID."""
        now = my_lib.time.now()
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
                msg = "Failed to get session ID after insert"
                raise RuntimeError(msg)
            logger.info(f"Started metrics session {session_id}")
            return session_id

    def update_heartbeat(self, session_id: int) -> None:
        """Update session heartbeat timestamp."""
        now = my_lib.time.now()
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
        """Update session item and product counts."""
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
        """Increment round count for a session and return the new value."""
        current_unique_products = self.get_unique_product_count_for_session(session_id)
        current_total_items = self.get_total_item_count_for_session(session_id)
        now = my_lib.time.now()

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
            cursor = conn.execute(
                "SELECT round_count FROM crawl_sessions WHERE id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            return row["round_count"] if row else 0

    def mark_work_ended(self, session_id: int) -> None:
        """Mark when actual crawl work has ended (before sleep interval)."""
        now = my_lib.time.now()
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
        """End a crawl session."""
        now = my_lib.time.now()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT started_at FROM crawl_sessions WHERE id = ?",
                (session_id,),
            )
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
                logger.info(f"Ended metrics session {session_id}: {exit_reason}")

    def close_interrupted_sessions(self) -> int:
        """Close any sessions that were interrupted (ended_at IS NULL)."""
        now = my_lib.time.now()
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
                if row["last_heartbeat_at"]:
                    ended_at = datetime.fromisoformat(row["last_heartbeat_at"])
                else:
                    ended_at = now
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
                logger.warning(f"Closed interrupted session {session_id} (was started at {started_at})")

            conn.commit()
            return closed_count

    def get_session(self, session_id: int) -> CrawlSession | None:
        """Get session by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM crawl_sessions WHERE id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return self._row_to_session(row) if row else None

    def get_current_session(self) -> CrawlSession | None:
        """Get currently running session (if any)."""
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
        """Get recent sessions."""
        since = my_lib.time.now() - timedelta(days=days)
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

    # Store statistics
    def record_store_stats(
        self,
        session_id: int,
        store_name: str,
        total_items: int,
        success_count: int,
        failed_count: int,
        total_duration_sec: float,
    ) -> None:
        """Record or update store-level statistics."""
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
        """Get store statistics for a session."""
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

    def get_store_aggregate_stats(self, days: int = 30) -> list[StoreAggregateStats]:
        """Get aggregated store statistics over the specified period."""
        since = my_lib.time.now() - timedelta(days=days)
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

                avg_duration = total_duration_sec / success_count if success_count > 0 else 0.0
                success_rate = success_count / total_items if total_items > 0 else 0.0

                results.append(
                    StoreAggregateStats(
                        store_name=row["store_name"],
                        total_sessions=row["total_sessions"],
                        total_items=total_items,
                        success_count=success_count,
                        failed_count=failed_count,
                        total_duration_sec=total_duration_sec,
                        avg_duration_sec=avg_duration,
                        success_rate=success_rate,
                    )
                )
            return results

    # Item statistics
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
        """Record item-level crawl statistics."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO item_crawl_stats
                    (session_id, store_name, product_id, started_at, duration_sec, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    store_name,
                    product_id,
                    started_at.isoformat(),
                    duration_sec,
                    success,
                    error_message,
                ),
            )
            conn.commit()

    def get_item_stats_for_session(self, session_id: int) -> list[ItemCrawlStats]:
        """Get item statistics for a session."""
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

    def get_store_durations(self, store_name: str, days: int = 30, limit: int = 1000) -> list[float]:
        """Get individual item durations for a store (for boxplot)."""
        since = my_lib.time.now() - timedelta(days=days)
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

    # Amazon batch statistics
    def record_amazon_batch(
        self,
        session_id: int,
        started_at: datetime,
        duration_sec: float | None,
        product_count: int,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Record Amazon API batch statistics."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO amazon_batch_stats
                    (session_id, started_at, duration_sec, product_count, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    started_at.isoformat(),
                    duration_sec,
                    product_count,
                    success,
                    error_message,
                ),
            )
            conn.commit()

    def get_amazon_batch_stats(self, days: int = 30) -> list[AmazonBatchStats]:
        """Get Amazon batch statistics over the specified period."""
        since = my_lib.time.now() - timedelta(days=days)
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

    # Heatmap data
    def get_heatmap_data(self, days: int = 90) -> list[HeatmapEntry]:
        """Get heatmap data for crawl activity (30-minute intervals)."""
        since = my_lib.time.now() - timedelta(days=days)
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

    # Failure timeseries
    def get_failure_timeseries(self, days: int = 30) -> list[dict]:
        """Get failure count timeseries data."""
        since = my_lib.time.now() - timedelta(days=days)
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

    # Cycle statistics
    def get_unique_product_count_for_session(self, session_id: int) -> int:
        """Get the number of unique products processed in a session."""
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

    def get_total_item_count_for_session(self, session_id: int) -> int:
        """Get total item count for a session (item_crawl_stats + amazon_batch_stats)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM item_crawl_stats WHERE session_id = ?",
                (session_id,),
            )
            item_count = cursor.fetchone()["cnt"]

            cursor = conn.execute(
                "SELECT COALESCE(SUM(product_count), 0) as cnt FROM amazon_batch_stats WHERE session_id = ?",
                (session_id,),
            )
            amazon_count = cursor.fetchone()["cnt"]

            return item_count + amazon_count

    def calculate_cycle_stats(
        self,
        session: CrawlSession,
        total_product_count: int,
    ) -> CycleStats:
        """Calculate cycle statistics for a session."""
        unique_product_count = self.get_unique_product_count_for_session(session.id)
        total_item_count = self.get_total_item_count_for_session(session.id)

        completed_cycles = session.round_count
        current_cycle_stores = total_item_count - session.round_start_store_count

        if completed_cycles == 0:
            current_cycle_products = unique_product_count - session.round_start_product_count
        elif current_cycle_stores > 0 and unique_product_count > 0:
            avg_stores_per_product = (
                total_item_count / unique_product_count if unique_product_count > 0 else 1
            )
            estimated_products = int(current_cycle_stores / avg_stores_per_product)
            current_cycle_products = min(total_product_count, estimated_products)
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
                work_duration = (my_lib.time.now() - session.started_at).total_seconds()

            cycle_duration_sec = work_duration / completed_cycles

        cumulative_product_count = unique_product_count * completed_cycles + current_cycle_products

        return CycleStats(
            completed_cycles=completed_cycles,
            cycle_duration_sec=cycle_duration_sec,
            unique_product_count=unique_product_count,
            total_product_count=total_product_count,
            current_cycle_products=current_cycle_products,
            current_cycle_stores=current_cycle_stores,
            total_item_count=total_item_count,
            cumulative_product_count=cumulative_product_count,
        )

    # Session status for API
    def get_session_status(self, total_product_count: int = 0) -> SessionStatus:
        """Get current session status for API response."""
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
        """Check if crawler is healthy based on session heartbeat."""
        session = self.get_current_session()
        if session is None:
            logger.warning("No active session found")
            return False

        if session.last_heartbeat_at is None:
            logger.warning("Session has no heartbeat")
            return False

        now = my_lib.time.now()
        elapsed = (now - session.last_heartbeat_at).total_seconds()
        if elapsed > max_age_sec:
            logger.warning(f"Heartbeat too old: {elapsed:.1f}s (max: {max_age_sec}s)")
            return False

        return True

    # Cleanup
    def cleanup_old_records(self, days: int = 365) -> int:
        """Delete records older than specified days."""
        cutoff = my_lib.time.now() - timedelta(days=days)
        total_deleted = 0

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM crawl_sessions WHERE started_at < ?",
                (cutoff.isoformat(),),
            )
            old_session_ids = [row["id"] for row in cursor.fetchall()]

            if old_session_ids:
                placeholders = ",".join("?" * len(old_session_ids))

                cursor = conn.execute(
                    f"DELETE FROM item_crawl_stats WHERE session_id IN ({placeholders})",  # noqa: S608
                    old_session_ids,
                )
                total_deleted += cursor.rowcount

                cursor = conn.execute(
                    f"DELETE FROM store_crawl_stats WHERE session_id IN ({placeholders})",  # noqa: S608
                    old_session_ids,
                )
                total_deleted += cursor.rowcount

                cursor = conn.execute(
                    f"DELETE FROM amazon_batch_stats WHERE session_id IN ({placeholders})",  # noqa: S608
                    old_session_ids,
                )
                total_deleted += cursor.rowcount

                cursor = conn.execute(
                    f"DELETE FROM crawl_sessions WHERE id IN ({placeholders})",  # noqa: S608
                    old_session_ids,
                )
                total_deleted += cursor.rowcount

                conn.commit()

        if total_deleted > 0:
            logger.info(f"Deleted {total_deleted} old metrics records")
        return total_deleted

    # Row converters
    def _row_to_session(self, row: sqlite3.Row) -> CrawlSession:
        """Convert database row to CrawlSession."""
        row_dict: dict[str, Any] = dict(row)
        return CrawlSession(
            id=row_dict["id"],
            started_at=datetime.fromisoformat(row_dict["started_at"]),
            last_heartbeat_at=(
                datetime.fromisoformat(row_dict["last_heartbeat_at"])
                if row_dict["last_heartbeat_at"]
                else None
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
        """Convert database row to ItemCrawlStats."""
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
        """Convert database row to AmazonBatchStats."""
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

