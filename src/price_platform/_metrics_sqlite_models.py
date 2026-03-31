"""Shared data models for SQLite-backed crawl metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import my_lib.time

LockingMode = Literal["NORMAL", "EXCLUSIVE"]

HEARTBEAT_TIMEOUT_SEC = 600


@dataclass(frozen=True)
class CrawlSession:
    """Crawl session data."""

    id: int
    started_at: datetime
    last_heartbeat_at: datetime | None
    ended_at: datetime | None
    work_ended_at: datetime | None
    duration_sec: float | None
    total_items: int
    success_items: int
    failed_items: int
    total_products: int
    success_products: int
    round_count: int
    round_start_product_count: int
    round_start_store_count: int
    last_round_completed_at: datetime | None
    exit_reason: str | None

    @property
    def is_running(self) -> bool:
        if self.ended_at is not None:
            return False
        return not self.is_timed_out

    @property
    def is_timed_out(self) -> bool:
        if self.ended_at is not None:
            return False
        if self.last_heartbeat_at is None:
            return True
        elapsed = (my_lib.time.now() - self.last_heartbeat_at).total_seconds()
        return elapsed > HEARTBEAT_TIMEOUT_SEC

    @property
    def effective_exit_reason(self) -> str | None:
        if self.exit_reason is not None:
            return self.exit_reason
        if self.is_timed_out:
            return "timeout"
        return None


@dataclass(frozen=True)
class StoreCrawlStats:
    store_name: str
    total_items: int
    success_count: int
    failed_count: int
    total_duration_sec: float

    @property
    def success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.success_count / self.total_items

    @property
    def avg_duration_sec(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_duration_sec / self.success_count


@dataclass(frozen=True)
class ItemCrawlStats:
    id: int
    session_id: int
    store_name: str
    product_id: str
    started_at: datetime
    duration_sec: float | None
    success: bool
    error_message: str | None


@dataclass(frozen=True)
class AmazonBatchStats:
    id: int
    session_id: int
    started_at: datetime
    duration_sec: float | None
    product_count: int
    success: bool
    error_message: str | None


@dataclass
class CycleStats:
    completed_cycles: int
    cycle_duration_sec: float | None
    unique_product_count: int
    total_product_count: int
    current_cycle_products: int = 0
    current_cycle_stores: int = 0
    total_item_count: int = 0
    cumulative_product_count: int = 0


@dataclass
class SessionStatus:
    is_running: bool
    session_id: int | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    processed_items: int = 0
    success_items: int = 0
    failed_items: int = 0
    processed_products: int = 0
    success_products: int = 0
    cycle_stats: CycleStats | None = None


@dataclass
class HeatmapEntry:
    date: str
    slot: int
    item_count: int
    success_count: int
    failed_count: int
    total_duration_sec: float

    @property
    def success_rate(self) -> float:
        if self.item_count == 0:
            return 0.0
        return self.success_count / self.item_count


@dataclass
class StoreAggregateStats:
    store_name: str
    total_sessions: int
    total_items: int
    success_count: int
    failed_count: int
    total_duration_sec: float
    avg_duration_sec: float
    success_rate: float
    durations: list[float] = field(default_factory=list)
