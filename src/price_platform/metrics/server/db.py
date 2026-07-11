"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

import collections.abc
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..._singleton import SingletonHolder
from ...schema_registry import resolve_schema_path
from ...sqlite_store import SQLiteStoreBase
from .migrations import METRICS_MIGRATIONS
from .models import (
    HEARTBEAT_TIMEOUT_SEC,
    AmazonBatchStats,
    CrawlSession,
    CycleStats,
    HeatmapEntry,
    ItemCrawlStats,
    LockingMode,
    SessionStatus,
    StoreAggregateStats,
    StoreCrawlStats,
)
from .reads import MetricsDBReadMixin
from .writes import MetricsDBWriteMixin

if TYPE_CHECKING:
    pass


class MetricsDB(MetricsDBWriteMixin, MetricsDBReadMixin, SQLiteStoreBase):
    """SQLite-based metrics data store."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path | None = None,
        *,
        locking_mode: LockingMode = "NORMAL",
    ):
        # ClientMetricsDB と同様に接続をロックで直列化し、
        # マルチスレッド利用時の方針を統一する (R10)
        self._lock = threading.RLock()
        super().__init__(
            db_path=db_path,
            schema_path=schema_path or resolve_schema_path("sqlite_metrics.schema"),
            locking_mode=locking_mode,
            migrations=METRICS_MIGRATIONS,
        )

    @contextmanager
    def _get_connection(self) -> collections.abc.Iterator[sqlite3.Connection]:
        with self._lock, self.connection() as conn:
            yield conn


def open_metrics_db(db_path: pathlib.Path) -> MetricsDB:
    """Create a metrics database without touching any global singleton."""
    return MetricsDB(db_path)


_metrics_db_holder: SingletonHolder[MetricsDB] = SingletonHolder("MetricsDB", "init_metrics_db()")


def get_metrics_db() -> MetricsDB:
    """Return the global metrics database instance."""
    return _metrics_db_holder.get()


def init_metrics_db(db_path: pathlib.Path) -> MetricsDB:
    """Initialize and return the global metrics database instance."""
    return _metrics_db_holder.set(open_metrics_db(db_path))


def _reset_metrics_db() -> None:
    """Reset the global metrics database instance for tests."""
    _metrics_db_holder.reset()


__all__ = [
    "HEARTBEAT_TIMEOUT_SEC",
    "AmazonBatchStats",
    "CrawlSession",
    "CycleStats",
    "HeatmapEntry",
    "ItemCrawlStats",
    "LockingMode",
    "MetricsDB",
    "SessionStatus",
    "StoreAggregateStats",
    "StoreCrawlStats",
    "get_metrics_db",
    "init_metrics_db",
    "open_metrics_db",
]
