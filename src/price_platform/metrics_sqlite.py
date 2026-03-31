"""Shared SQLite-backed metrics persistence."""

from __future__ import annotations

import pathlib
import sqlite3
from typing import TYPE_CHECKING

from ._metrics_sqlite_models import LockingMode
from .metrics_sqlite_reads import MetricsDBReadMixin
from .metrics_sqlite_writes import MetricsDBWriteMixin
from .sqlite_store import SQLiteStoreBase

if TYPE_CHECKING:
    from collections.abc import Generator


class MetricsDB(MetricsDBWriteMixin, MetricsDBReadMixin, SQLiteStoreBase):
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
