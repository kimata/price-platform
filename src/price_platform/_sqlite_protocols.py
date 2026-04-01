"""Shared protocols for SQLite-backed mixins."""

from __future__ import annotations

from collections.abc import Generator
from typing import Protocol
import sqlite3

from ._client_metrics_sqlite_models import BoxplotData, ClientPerfRaw, DeviceType, MetricName, WebVitalBoxplotData, WebVitalName
from ._metrics_sqlite_models import AmazonBatchStats, CrawlSession, ItemCrawlStats


class SQLiteConnectionProvider(Protocol):
    """Provide SQLite connections to mixins."""

    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]: ...


class ClientMetricsAggregateProvider(SQLiteConnectionProvider, Protocol):
    """Connection plus daily aggregation state for client metrics."""

    _last_aggregated_date: str | None

    def aggregate_web_vitals_daily(self, date: str) -> int: ...


class ClientMetricsBoxplotProvider(SQLiteConnectionProvider, Protocol):
    """Surface required by client metric boxplot helpers."""

    def _compute_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: MetricName,
        device_type: DeviceType,
    ) -> BoxplotData | None: ...


class ClientMetricsWebVitalsProvider(SQLiteConnectionProvider, Protocol):
    """Surface required by web vitals query helpers."""

    def _compute_web_vital_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: WebVitalName,
        device_type: DeviceType,
    ) -> WebVitalBoxplotData | None: ...


class MetricsRowMapper(SQLiteConnectionProvider, Protocol):
    """Connection plus row mapping for metrics readers."""

    def _row_to_session(self, row: sqlite3.Row) -> CrawlSession: ...

    def _row_to_item_stats(self, row: sqlite3.Row) -> ItemCrawlStats: ...

    def _row_to_amazon_batch(self, row: sqlite3.Row) -> AmazonBatchStats: ...

