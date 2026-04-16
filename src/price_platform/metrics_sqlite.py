"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

import collections.abc
import pathlib
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ._metrics_sqlite_models import (
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
from .metrics_sqlite_reads import MetricsDBReadMixin
from .metrics_sqlite_writes import MetricsDBWriteMixin
from .schema_registry import resolve_schema_path
from .sqlite_store import SQLiteStoreBase

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
        super().__init__(
            db_path=db_path,
            schema_path=schema_path or resolve_schema_path("sqlite_metrics.schema"),
            locking_mode=locking_mode,
        )

    @contextmanager
    def _get_connection(self) -> collections.abc.Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            yield conn


def open_metrics_db(db_path: pathlib.Path) -> MetricsDB:
    """Create a metrics database without touching any global singleton."""
    return MetricsDB(db_path)


_metrics_db: MetricsDB | None = None


def get_metrics_db() -> MetricsDB:
    """Return the global metrics database instance."""
    if _metrics_db is None:
        raise RuntimeError("MetricsDB not initialized. Call init_metrics_db() first.")
    return _metrics_db


def init_metrics_db(db_path: pathlib.Path) -> MetricsDB:
    """Initialize and return the global metrics database instance."""
    global _metrics_db
    _metrics_db = open_metrics_db(db_path)
    return _metrics_db


def _reset_metrics_db() -> None:
    """Reset the global metrics database instance for tests."""
    global _metrics_db
    _metrics_db = None


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
