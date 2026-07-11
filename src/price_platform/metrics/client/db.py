"""Shared client-side performance metrics collection and aggregation."""

from __future__ import annotations

import collections.abc
import logging
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..._singleton import SingletonHolder
from ...migrations import build_client_metrics_migrations
from ...schema_registry import resolve_schema_path
from ...sqlite_store import SQLiteStoreBase
from ..render.boxplot_svg import generate_boxplot_svg
from .boxplot import ClientMetricsBoxplotMixin
from .models import (
    BoxplotData,
    ClientPerfDaily,
    ClientPerfRaw,
    DeviceType,
    MetricName,
    SocialReferralEventRaw,
    WebVitalBoxplotData,
    WebVitalDaily,
    WebVitalName,
    WebVitalRaw,
    detect_device_type,
)
from .social_referrals import ClientMetricsSocialReferralMixin
from .web_vitals import ClientMetricsWebVitalsReadMixin, ClientMetricsWebVitalsWriteMixin
from .writes import ClientMetricsWriteMixin

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


class ClientMetricsDB(
    ClientMetricsWriteMixin,
    ClientMetricsBoxplotMixin,
    ClientMetricsSocialReferralMixin,
    ClientMetricsWebVitalsWriteMixin,
    ClientMetricsWebVitalsReadMixin,
    SQLiteStoreBase,
):
    """SQLite database for client performance metrics."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_path: pathlib.Path | None = None,
    ):
        self._lock = threading.RLock()
        self._last_aggregated_date: str | None = None  # type: ignore[assignment]  # mixin infers str, Protocol is str | None
        super().__init__(
            db_path=db_path,
            schema_path=schema_path or resolve_schema_path("sqlite_client_metrics.schema"),
            migrations=build_client_metrics_migrations(),
        )

    @contextmanager
    def _get_connection(self) -> collections.abc.Iterator[sqlite3.Connection]:
        with self._lock, self.connection() as conn:
            yield conn


def open_client_metrics_db(db_path: pathlib.Path) -> ClientMetricsDB:
    """Create a client metrics database without touching any global singleton."""
    return ClientMetricsDB(db_path)


_client_metrics_db_holder: SingletonHolder[ClientMetricsDB] = SingletonHolder(
    "ClientMetricsDB", "init_client_metrics_db()"
)


def get_client_metrics_db() -> ClientMetricsDB:
    """Return the global client metrics database instance."""
    return _client_metrics_db_holder.get()


def init_client_metrics_db(db_path: pathlib.Path) -> ClientMetricsDB:
    """Initialize and return the global client metrics database instance."""
    return _client_metrics_db_holder.set(open_client_metrics_db(db_path))


def _reset_client_metrics_db() -> None:
    """Reset the global client metrics database instance for tests."""
    _client_metrics_db_holder.reset()

__all__ = [
    "BoxplotData",
    "ClientMetricsDB",
    "ClientPerfDaily",
    "ClientPerfRaw",
    "DeviceType",
    "MetricName",
    "SocialReferralEventRaw",
    "WebVitalBoxplotData",
    "WebVitalDaily",
    "WebVitalName",
    "WebVitalRaw",
    "detect_device_type",
    "generate_boxplot_svg",
    "get_client_metrics_db",
    "init_client_metrics_db",
    "open_client_metrics_db",
]
