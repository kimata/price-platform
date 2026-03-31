"""Shared client-side performance metrics collection and aggregation."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
import threading

from .client_metrics_boxplot import ClientMetricsBoxplotMixin
from .client_metrics_svg import generate_boxplot_svg
from .client_metrics_web_vitals import ClientMetricsWebVitalsReadMixin, ClientMetricsWebVitalsWriteMixin
from .client_metrics_writes import ClientMetricsWriteMixin

logger = logging.getLogger(__name__)


class ClientMetricsDB(
    ClientMetricsWriteMixin,
    ClientMetricsBoxplotMixin,
    ClientMetricsWebVitalsWriteMixin,
    ClientMetricsWebVitalsReadMixin,
):
    """SQLite database for client performance metrics."""

    def __init__(self, db_path: pathlib.Path, schema_path: pathlib.Path):
        self.db_path = db_path
        self.schema_path = schema_path
        self._lock = threading.Lock()
        self._last_aggregated_date: str | None = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                with self.schema_path.open() as f:
                    schema = f.read()
                conn.executescript(schema)
                conn.commit()
            finally:
                conn.close()

__all__ = ["ClientMetricsDB", "generate_boxplot_svg"]
