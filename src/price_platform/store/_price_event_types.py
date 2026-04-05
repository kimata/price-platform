"""Shared types for price event detection."""

from __future__ import annotations

from collections.abc import Mapping
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
    def get_price_history(self, product_id: str, days: int) -> list[PriceRecordT]: ...
    def get_lowest_price(self, product_id: str, *, is_used: bool) -> PriceRecordT | None: ...
    def get_sold_records(self, product_id: str, *, limit: int = 20) -> list[SoldRecordT]: ...
    def get_current_prices(self, product_id: str) -> list[PriceRecordT]: ...


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
        }
        payload.update(self.extra_fields)
        return payload


class EventFactoryProtocol(Protocol[PriceEventT_co]):
    def create_event(self, draft: PriceEventDraft) -> PriceEventT_co: ...


class EventMetadataAdapter(Protocol[PriceRecordT_contra]):
    def __call__(self, record: PriceRecordT_contra) -> Mapping[str, object | None]: ...


class DetectedPriceEventProtocol(Protocol):
    id: int | None
    event_type: Any
    priority: int
    product_id: str
    store: Any
    price: int


@dataclass
class PriceContext(Generic[PriceRecordT, SoldRecordT]):
    """Aggregated price data for event detection."""

    product_id: str
    current_prices: list[PriceRecordT]
    new_prices: list[PriceRecordT]
    used_prices: list[PriceRecordT]
    all_time_lowest_new: PriceRecordT | None
    period_lowest: dict[int, PriceRecordT | None]
    price_history: dict[int, list[PriceRecordT]]
    sold_records: list[SoldRecordT]


@dataclass
class PriceEventConfig:
    """Configuration for price event detection."""

    period_low_days: tuple[int, ...] = (30, 60, 90, 180, 365)
    price_drop_threshold_percent: float = 10.0
    good_used_ratio_max: float = 0.5
    flea_bargain_threshold_percent: float = 20.0
    price_recovery_threshold_percent: float = 5.0
    price_recovery_min_days_after_low: int = 7
    price_recovery_consecutive_rises: int = 3
    price_recovery_consecutive_min_percent: float = 5.0
    suppression_window_hours: int = 24
    same_price_suppression_days: int = 14
    same_price_tolerance: int = 100
