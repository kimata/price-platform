"""Shared client-side performance metrics collection and aggregation."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ._client_metrics_sqlite_models import (
    BoxplotData,
    ClientPerfDaily,
    ClientPerfRaw,
    DeviceType,
    MetricName,
    WebVitalBoxplotData,
    WebVitalDaily,
    WebVitalName,
    WebVitalRaw,
    detect_device_type,
)
from .client_metrics_boxplot import ClientMetricsBoxplotMixin
from .client_metrics_svg import generate_boxplot_svg
from .client_metrics_web_vitals import ClientMetricsWebVitalsReadMixin, ClientMetricsWebVitalsWriteMixin
from .client_metrics_writes import ClientMetricsWriteMixin
from .schema_registry import resolve_schema_path
from .sqlite_store import SQLiteStoreBase

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Generator


class ClientMetricsDB(
    ClientMetricsWriteMixin,
    ClientMetricsBoxplotMixin,
    ClientMetricsWebVitalsWriteMixin,
    ClientMetricsWebVitalsReadMixin,
    SQLiteStoreBase,
):
    """SQLite database for client performance metrics."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path | None = None,
        *,
        schema_dir: pathlib.Path | None = None,
    ):
        self._lock = threading.RLock()
        self._last_aggregated_date: str | None = None
        super().__init__(
            db_path=db_path,
            schema_path=schema_path or resolve_schema_path("sqlite_client_metrics.schema", schema_dir=schema_dir),
        )

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        with self._lock:
            with self.connection() as conn:
                yield conn

__all__ = [
    "BoxplotData",
    "ClientMetricsDB",
    "ClientPerfDaily",
    "ClientPerfRaw",
    "DeviceType",
    "MetricName",
    "WebVitalBoxplotData",
    "WebVitalDaily",
    "WebVitalName",
    "WebVitalRaw",
    "detect_device_type",
    "generate_boxplot_svg",
]
