"""Shared types for price event detection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, Protocol, TypeVar

StoreTypeT = TypeVar("StoreTypeT")
StoreTypeT_co = TypeVar("StoreTypeT_co", covariant=True)
PriceEventT = TypeVar("PriceEventT", bound="DetectedPriceEventProtocol")
PriceEventT_co = TypeVar("PriceEventT_co", bound="DetectedPriceEventProtocol", covariant=True)
PriceRecordT = TypeVar("PriceRecordT", bound="PriceRecordProtocol[Any]")
PriceRecordT_contra = TypeVar("PriceRecordT_contra", bound="PriceRecordProtocol[Any]", contravariant=True)
SoldRecordT = TypeVar("SoldRecordT", bound="SoldRecordProtocol")


class PriceRecordProtocol(Protocol[StoreTypeT_co]):
    @property
    def price(self) -> int: ...
    @property
    def is_used(self) -> bool: ...
    @property
    def store(self) -> StoreTypeT_co: ...
    @property
    def url(self) -> str | None: ...
    @property
    def recorded_at(self) -> datetime: ...


class SoldRecordProtocol(Protocol):
    @property
    def price(self) -> int: ...


class PriceStoreProtocol(Protocol[PriceRecordT, SoldRecordT]):
    def get_price_history(
        self, product_id: str, days: int, *, selection_key: str | None = None
    ) -> list[PriceRecordT]: ...
    def get_lowest_price(
        self, product_id: str, *, is_used: bool, selection_key: str | None = None
    ) -> PriceRecordT | None: ...
    def get_sold_records(
        self, product_id: str, *, limit: int = 20, selection_key: str | None = None
    ) -> list[SoldRecordT]: ...
    def get_current_prices(
        self, product_id: str, *, selection_key: str | None = None
    ) -> list[PriceRecordT]: ...


class PriceEventStoreProtocol(Protocol[PriceEventT]):
    def has_recent_similar_price_event(
        self,
        product_id: str,
        store: Any,
        price: int,
        days: int = 14,
        tolerance: int = 100,
    ) -> bool: ...
    def get_recent_event_for_product(self, product_id: str, hours: int) -> PriceEventT | None: ...
    def save_event(self, event: PriceEventT) -> int: ...
    def suppress_event(self, event_id: int, superseded_by: int) -> None: ...


@dataclass(frozen=True)
class PriceEventDraft:
    """Typed event DTO used inside the shared detector."""

    event_type: Any
    product_id: str
    store: Any
    price: int
    url: str | None
    recorded_at: datetime
    previous_price: int | None = None
    reference_price: int | None = None
    change_percent: float | None = None
    period_days: int | None = None
    percentile_rank: float | None = None
    rarity_tier: str | None = None
    baseline_price: int | None = None
    sample_days: int | None = None
    sample_count: int | None = None
    rarity_window_days: int | None = None
    detector_version: str | None = None
    canonical_variant_key: str | None = None
    event_family: str | None = None
    comparison_basis: str | None = None
    severity: str | None = None
    extra_fields: Mapping[str, object | None] = field(default_factory=dict)

    def to_kwargs(self) -> dict[str, object | None]:
        payload: dict[str, object | None] = {
            "event_type": self.event_type,
            "product_id": self.product_id,
            "store": self.store,
            "price": self.price,
            "url": self.url,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "change_percent": self.change_percent,
            "period_days": self.period_days,
            "recorded_at": self.recorded_at,
            "percentile_rank": self.percentile_rank,
            "rarity_tier": self.rarity_tier,
            "baseline_price": self.baseline_price,
            "sample_days": self.sample_days,
            "sample_count": self.sample_count,
            "rarity_window_days": self.rarity_window_days,
            "detector_version": self.detector_version,
            "canonical_variant_key": self.canonical_variant_key,
            "event_family": self.event_family,
            "comparison_basis": self.comparison_basis,
            "severity": self.severity,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        payload.update(self.extra_fields)
        return payload


class EventFactoryProtocol(Protocol[PriceEventT_co]):
    def create_event(self, draft: PriceEventDraft) -> PriceEventT_co: ...


class EventMetadataAdapter(Protocol[PriceRecordT_contra]):
    def __call__(self, record: PriceRecordT_contra) -> Mapping[str, object | None]: ...


class DetectedPriceEventProtocol(Protocol):
    @property
    def id(self) -> int | None: ...
    @property
    def event_type(self) -> Any: ...
    @property
    def priority(self) -> int: ...
    @property
    def product_id(self) -> str: ...
    @property
    def store(self) -> Any: ...
    @property
    def price(self) -> int: ...


@dataclass
class PriceContext(Generic[PriceRecordT, SoldRecordT]):
    """Aggregated price data for event detection."""

    product_id: str
    canonical_variant_key: str | None
    current_prices: list[PriceRecordT]
    new_prices: list[PriceRecordT]
    used_prices: list[PriceRecordT]
    all_time_lowest_new: PriceRecordT | None
    period_lowest: dict[int, PriceRecordT | None]
    price_history: dict[int, list[PriceRecordT]]
    stable_price_history: dict[int, list[PriceHistoryPoint]]
    full_new_price_history: list[PriceRecordT]
    stable_full_new_price_history: list[PriceHistoryPoint]
    sold_records: list[SoldRecordT]


@dataclass(frozen=True)
class PriceHistoryPoint:
    price: int
    recorded_at: datetime


def default_canonical_variant_key_builder(
    product_id: str,
    current_prices: Sequence[PriceRecordProtocol[Any]],
) -> str | None:
    del current_prices
    return product_id


def _no_variant_key(_record: Any) -> None:
    return None


@dataclass
class PriceEventConfig:
    """Configuration for price event detection."""

    variant_key_extractor: Callable[[Any], str | None] = _no_variant_key
    canonical_variant_key_builder: Callable[[str, Sequence[PriceRecordProtocol[Any]]], str | None] = (
        default_canonical_variant_key_builder
    )
    period_low_days: tuple[int, ...] = (30, 60, 90, 180, 365)
    daily_price_mode: str = "median"
    rarity_window_days: int = 365
    rarity_min_coverage_ratio: float = 0.3
    rarity_confidence_z_score: float = 1.96
    moderate_rarity_max_percentile: float = 25.0
    high_rarity_max_percentile: float = 10.0
    very_high_rarity_max_percentile: float = 5.0
    extreme_rarity_max_percentile: float = 1.0
    price_drop_threshold_percent: float = 10.0
    price_drop_large_threshold_percent: float = 20.0
    price_drop_baseline_window_days: int = 14
    price_drop_exclude_recent_days: int = 2
    price_drop_support_window_days: int = 3
    price_drop_support_min_observations: int = 2
    price_drop_spike_threshold_percent: float = 15.0
    price_drop_baseline_band_percent: float = 3.0
    good_used_ratio_max: float = 0.5
    flea_bargain_threshold_percent: float = 20.0
    price_recovery_threshold_percent: float = 5.0
    price_recovery_min_days_after_low: int = 7
    price_recovery_window_days: int = 30
    price_recovery_consecutive_rises: int = 3
    price_recovery_consecutive_min_percent: float = 5.0
    all_time_low_min_days: int = 30
    suppression_window_hours: int = 24
    same_price_suppression_days: int = 14
    same_price_tolerance: int = 100
    detector_version: str = "v2"
