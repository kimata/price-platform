"""Cross-app helper builders for consumer applications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import price_platform.store_runtime
import price_platform.webapp

ConfigT = TypeVar("ConfigT")
PriceStoreT = TypeVar("PriceStoreT")
PriceEventStoreT = TypeVar("PriceEventStoreT")
MetricsDbT = TypeVar("MetricsDbT")
ClientMetricsDbT = TypeVar("ClientMetricsDbT")
NotificationStoreT = TypeVar("NotificationStoreT")
WebPushStoreT = TypeVar("WebPushStoreT")


@dataclass(frozen=True)
class StoreRuntimeFactories(Generic[ConfigT, PriceStoreT, PriceEventStoreT]):
    """Factories for building a typed StoreRuntime."""

    price_store_factory: Callable[[ConfigT], PriceStoreT]
    price_event_store_factory: Callable[[ConfigT], PriceEventStoreT]


@dataclass(frozen=True)
class ServiceFactories(Generic[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]):
    """Factories for opening Web API service dependencies."""

    metrics_db_factory: Callable[[ConfigT], MetricsDbT | None]
    client_metrics_db_factory: Callable[[ConfigT], ClientMetricsDbT | None]
    notification_store_factory: Callable[[ConfigT], NotificationStoreT | None]
    webpush_store_factory: Callable[[ConfigT], WebPushStoreT | None]


def build_store_runtime(
    config: ConfigT,
    factories: StoreRuntimeFactories[ConfigT, PriceStoreT, PriceEventStoreT],
) -> price_platform.store_runtime.StoreRuntime[PriceStoreT, PriceEventStoreT]:
    """Build a typed StoreRuntime from store factories."""
    return price_platform.store_runtime.build_store_runtime(
        config,
        price_store_factory=factories.price_store_factory,
        price_event_store_factory=factories.price_event_store_factory,
    )


def build_app_services(
    config: ConfigT,
    factories: ServiceFactories[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
) -> price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]:
    """Build an AppServices bundle from service factories."""
    return price_platform.webapp.build_app_services(
        metrics_db_factory=lambda: factories.metrics_db_factory(config),
        client_metrics_db_factory=lambda: factories.client_metrics_db_factory(config),
        notification_store_factory=lambda: factories.notification_store_factory(config),
        webpush_store_factory=lambda: factories.webpush_store_factory(config),
    )
