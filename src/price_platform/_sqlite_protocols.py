"""SQLite ベースの mixin が参照する共通 Protocol 定義。"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Protocol

from ._client_metrics_sqlite_models import (
    BoxplotData,
    DeviceType,
    MetricName,
    WebVitalBoxplotData,
    WebVitalName,
)
from ._metrics_sqlite_models import AmazonBatchStats, CrawlSession, CycleStats, ItemCrawlStats


class SQLiteConnectionProvider(Protocol):
    """mixin へ SQLite 接続を供給するインターフェース。"""

    def _get_connection(self) -> AbstractContextManager[sqlite3.Connection]: ...


class ClientMetricsAggregateProvider(SQLiteConnectionProvider, Protocol):
    """クライアントメトリクスの日次集計に必要な状態を持つインターフェース。"""

    _last_aggregated_date: str | None

    def aggregate_daily(self, date: str) -> int: ...

    def aggregate_web_vitals_daily(self, date: str) -> int: ...


class ClientMetricsBoxplotProvider(SQLiteConnectionProvider, Protocol):
    """クライアントメトリクスの箱ひげ図集計で必要なインターフェース。"""

    def _compute_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: MetricName,
        device_type: DeviceType,
    ) -> BoxplotData | None: ...


class ClientMetricsWebVitalsProvider(SQLiteConnectionProvider, Protocol):
    """Web Vitals 集計で必要なインターフェース。"""

    def _compute_web_vital_stats_for_date(
        self,
        conn: sqlite3.Connection,
        date_str: str,
        metric_name: WebVitalName,
        device_type: DeviceType,
    ) -> WebVitalBoxplotData | None: ...


class MetricsRowMapper(SQLiteConnectionProvider, Protocol):
    """メトリクス読み取り時の行変換を備えたインターフェース。"""

    def _row_to_session(self, row: sqlite3.Row) -> CrawlSession: ...

    def _row_to_item_stats(self, row: sqlite3.Row) -> ItemCrawlStats: ...

    def _row_to_amazon_batch(self, row: sqlite3.Row) -> AmazonBatchStats: ...

    def get_current_session(self) -> CrawlSession | None: ...

    def get_unique_product_count_for_session(self, session_id: int) -> int: ...

    def get_total_item_count_for_session(self, session_id: int) -> int: ...

    def calculate_cycle_stats(self, session: CrawlSession, total_product_count: int) -> CycleStats: ...
