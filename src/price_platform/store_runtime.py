"""ストア依存コンテナを組み立てる共通ヘルパー。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

ConfigT = TypeVar("ConfigT")
PriceStoreT = TypeVar("PriceStoreT")
PriceEventStoreT = TypeVar("PriceEventStoreT")


@dataclass(frozen=True)
class StoreRuntime(Generic[PriceStoreT, PriceEventStoreT]):
    """クローラと Web API で共有するストア依存の束。"""

    price_store: PriceStoreT
    price_event_store: PriceEventStoreT


def build_store_runtime(
    config: ConfigT,
    *,
    price_store_factory: Callable[[ConfigT], PriceStoreT],
    price_event_store_factory: Callable[[ConfigT], PriceEventStoreT],
) -> StoreRuntime[PriceStoreT, PriceEventStoreT]:
    """型付きストアファクトリーからランタイム依存を構築する。"""
    return StoreRuntime(
        price_store=price_store_factory(config),
        price_event_store=price_event_store_factory(config),
    )


def build_store_runtime_for(
    config: ConfigT,
    *,
    price_store_type: type[PriceStoreT],
    price_event_store_type: type[PriceEventStoreT],
) -> StoreRuntime[PriceStoreT, PriceEventStoreT]:
    """ストア型を直接指定してランタイム依存を構築する。"""
    return build_store_runtime(
        config,
        price_store_factory=price_store_type,
        price_event_store_factory=price_event_store_type,
    )
