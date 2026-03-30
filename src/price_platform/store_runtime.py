"""Generic helpers for store dependency containers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

ConfigT = TypeVar("ConfigT")
PriceStoreT = TypeVar("PriceStoreT")
PriceEventStoreT = TypeVar("PriceEventStoreT")


@dataclass(frozen=True)
class StoreRuntime(Generic[PriceStoreT, PriceEventStoreT]):
    """Store services used together by crawlers and Web APIs."""

    price_store: PriceStoreT
    price_event_store: PriceEventStoreT


def build_store_runtime(
    config: ConfigT,
    *,
    price_store_factory: Callable[[ConfigT], PriceStoreT],
    price_event_store_factory: Callable[[ConfigT], PriceEventStoreT],
) -> StoreRuntime[PriceStoreT, PriceEventStoreT]:
    """Build a store runtime from typed store factories."""
    return StoreRuntime(
        price_store=price_store_factory(config),
        price_event_store=price_event_store_factory(config),
    )
