"""Shared SQLite base for price-event stores."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generic, Literal, TypeVar

import my_lib.sqlite_util
import my_lib.time

LockingMode = Literal["NORMAL", "EXCLUSIVE"]

EventT = TypeVar("EventT")

logger = logging.getLogger(__name__)


class BasePriceEventStore(Generic[EventT]):
    """SQLite-backed event store with configurable selection column."""

    def __init__(
        self,
        *,
        db_path: Path,
        schema_dir: Path,
        selection_column: str | None,
        event_factory: Callable[[sqlite3.Row, str | None], EventT],
        locking_mode: LockingMode = "NORMAL",
        pre_schema_migrate: Callable[[sqlite3.Connection], None] | None = None,
    ):
        self._db_path = db_path
        self._schema_dir = schema_dir
        self._selection_column = selection_column
        self._event_factory = event_factory
        self._locking_mode = locking_mode

        if self._db_path.exists() and pre_schema_migrate is not None:
            with self._get_connection() as conn:
                pre_schema_migrate(conn)
                conn.commit()

        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        schema_path = self._schema_dir / "sqlite_price_events.schema"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        my_lib.sqlite_util.init_schema_from_file(self._db_path, schema_path, locking_mode=self._locking_mode)
        if self._selection_column is not None:
            self._ensure_selection_column()

    def _ensure_selection_column(self) -> None:
        assert self._selection_column is not None
        with self._get_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(price_events)").fetchall()}
            if self._selection_column not in columns:
                conn.execute(f"ALTER TABLE price_events ADD COLUMN {self._selection_column} TEXT")
                conn.commit()
                logger.info("Migrated price_events: added %s column", self._selection_column)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        with my_lib.sqlite_util.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def save_event(self, event: object) -> int:
        selection_sql = f"{self._selection_column}, " if self._selection_column else ""
        selection_placeholder = "?, " if self._selection_column else ""
        selection_value = getattr(event, self._selection_column) if self._selection_column else None

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO price_events
                    (event_type, priority, product_id, store, price, url,
                     previous_price, reference_price, change_percent, period_days,
                     {selection_sql}recorded_at, suppressed, superseded_by, twitter_posted, twitter_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {selection_placeholder}?, ?, ?, ?, ?)
                """,
                (
                    event.event_type.value,
                    event.priority,
                    event.product_id,
                    event.store.value,
                    event.price,
                    event.url,
                    event.previous_price,
                    event.reference_price,
                    event.change_percent,
                    event.period_days,
                    *((selection_value,) if self._selection_column else ()),
                    event.recorded_at.isoformat(),
                    event.suppressed,
                    event.superseded_by,
                    event.twitter_posted,
                    event.twitter_enabled,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_recent_event_for_product(self, product_id: str, hours: int = 24) -> EventT | None:
        since = my_lib.time.now() - timedelta(hours=hours)
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM price_events
                WHERE product_id = ? AND recorded_at >= ? AND suppressed = FALSE
                ORDER BY priority ASC, recorded_at DESC
                LIMIT 1
                """,
                (product_id, since.isoformat()),
            ).fetchone()
            return self._row_to_event(row) if row else None

    def suppress_event(self, event_id: int, superseded_by: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE price_events
                SET suppressed = TRUE, superseded_by = ?
                WHERE id = ?
                """,
                (superseded_by, event_id),
            )
            conn.commit()

    def get_events_for_product(
        self,
        product_id: str,
        limit: int = 100,
        offset: int = 0,
        include_suppressed: bool = False,
    ) -> list[EventT]:
        with self._get_connection() as conn:
            if include_suppressed:
                cursor = conn.execute(
                    """
                    SELECT * FROM price_events
                    WHERE product_id = ?
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (product_id, limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM price_events
                    WHERE product_id = ? AND suppressed = FALSE
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (product_id, limit, offset),
                )
            return [self._row_to_event(row) for row in cursor.fetchall()]

    def get_events_count_for_product(self, product_id: str, include_suppressed: bool = False) -> int:
        with self._get_connection() as conn:
            if include_suppressed:
                row = conn.execute("SELECT COUNT(*) FROM price_events WHERE product_id = ?", (product_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM price_events WHERE product_id = ? AND suppressed = FALSE",
                    (product_id,),
                ).fetchone()
            return row[0] if row else 0

    def get_recent_events(
        self,
        limit: int = 100,
        offset: int = 0,
        include_suppressed: bool = False,
    ) -> list[EventT]:
        with self._get_connection() as conn:
            if include_suppressed:
                cursor = conn.execute(
                    """
                    SELECT * FROM price_events
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM price_events
                    WHERE suppressed = FALSE
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
            )
            return [self._row_to_event(row) for row in cursor.fetchall()]

    def get_recent_events_for_products(
        self,
        product_ids: list[str],
        limit: int = 100,
        offset: int = 0,
        include_suppressed: bool = False,
    ) -> list[EventT]:
        if not product_ids:
            return []

        placeholders = ",".join("?" * len(product_ids))
        with self._get_connection() as conn:
            if include_suppressed:
                cursor = conn.execute(
                    f"""
                    SELECT * FROM price_events
                    WHERE product_id IN ({placeholders})
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,  # noqa: S608
                    (*product_ids, limit, offset),
                )
            else:
                cursor = conn.execute(
                    f"""
                    SELECT * FROM price_events
                    WHERE product_id IN ({placeholders}) AND suppressed = FALSE
                    ORDER BY recorded_at DESC
                    LIMIT ? OFFSET ?
                    """,  # noqa: S608
                    (*product_ids, limit, offset),
                )
            return [self._row_to_event(row) for row in cursor.fetchall()]

    def get_events_count_for_products(self, product_ids: list[str], include_suppressed: bool = False) -> int:
        if not product_ids:
            return 0

        placeholders = ",".join("?" * len(product_ids))
        with self._get_connection() as conn:
            if include_suppressed:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM price_events WHERE product_id IN ({placeholders})",  # noqa: S608
                    product_ids,
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM price_events"  # noqa: S608
                    f" WHERE product_id IN ({placeholders}) AND suppressed = FALSE",
                    product_ids,
                ).fetchone()
            return row[0] if row else 0

    def get_events_count(self, include_suppressed: bool = False) -> int:
        with self._get_connection() as conn:
            row = (
                conn.execute("SELECT COUNT(*) FROM price_events").fetchone()
                if include_suppressed
                else conn.execute("SELECT COUNT(*) FROM price_events WHERE suppressed = FALSE").fetchone()
            )
            return row[0] if row else 0

    def get_unposted_twitter_events(self, limit: int = 10) -> list[EventT]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM price_events
                WHERE twitter_posted = FALSE
                  AND twitter_enabled = TRUE
                  AND suppressed = FALSE
                ORDER BY priority ASC, recorded_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_event(row) for row in cursor.fetchall()]

    def mark_twitter_posted(self, event_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE price_events SET twitter_posted = TRUE WHERE id = ?", (event_id,))
            conn.commit()

    def has_recent_similar_price_event(
        self,
        product_id: str,
        store: object,
        price: int,
        days: int = 14,
        tolerance: int = 100,
    ) -> bool:
        since = my_lib.time.now() - timedelta(days=days)
        price_min = price - tolerance
        price_max = price + tolerance
        store_value = getattr(store, "value", store)
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM price_events
                WHERE product_id = ? AND store = ?
                  AND price >= ? AND price <= ?
                  AND recorded_at >= ?
                LIMIT 1
                """,
                (product_id, store_value, price_min, price_max, since.isoformat()),
            ).fetchone()
            return row is not None

    def cleanup_old_events(self, days: int = 365) -> int:
        cutoff = my_lib.time.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM price_events WHERE recorded_at < ?", (cutoff.isoformat(),))
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info("Deleted %s old price events", deleted)
            return deleted

    def delete_events_for_product(self, product_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM price_events WHERE product_id = ?", (product_id,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def delete_all_events(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM price_events")
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def get_all_product_ids(self) -> list[str]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT DISTINCT product_id FROM price_events ORDER BY product_id")
            return [row["product_id"] for row in cursor.fetchall()]

    def _row_to_event(self, row: sqlite3.Row) -> EventT:
        selection_value = None
        if self._selection_column is not None:
            try:
                selection_value = row[self._selection_column]
            except (IndexError, KeyError):
                selection_value = None
        return self._event_factory(row, selection_value)
