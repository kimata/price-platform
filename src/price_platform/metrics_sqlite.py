"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

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
    from collections.abc import Generator


class MetricsDB(MetricsDBWriteMixin, MetricsDBReadMixin, SQLiteStoreBase):
    """SQLite-based metrics data store."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path | None = None,
        *,
        schema_dir: pathlib.Path | None = None,
        locking_mode: LockingMode = "NORMAL",
    ):
        super().__init__(
            db_path=db_path,
            schema_path=schema_path or resolve_schema_path("sqlite_metrics.schema", schema_dir=schema_dir),
            locking_mode=locking_mode,
        )

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        with self.connection() as conn:
            yield conn


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
]
