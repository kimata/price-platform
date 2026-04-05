"""各アプリ共通で使うランタイム構築ヘルパー。"""

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
StoresT = TypeVar("StoresT")
ServicesT = TypeVar("ServicesT")


@dataclass(frozen=True)
class StoreRuntimeFactories(Generic[ConfigT, PriceStoreT, PriceEventStoreT]):
    """型付き `StoreRuntime` を構築するためのファクトリー群。"""

    price_store_factory: Callable[[ConfigT], PriceStoreT]
    price_event_store_factory: Callable[[ConfigT], PriceEventStoreT]


@dataclass(frozen=True)
class ServiceFactories(Generic[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]):
    """Web API が利用する依存サービスを生成するファクトリー群。"""

    metrics_db_factory: Callable[[ConfigT], MetricsDbT | None]
    client_metrics_db_factory: Callable[[ConfigT], ClientMetricsDbT | None]
    notification_store_factory: Callable[[ConfigT], NotificationStoreT | None]
    webpush_store_factory: Callable[[ConfigT], WebPushStoreT | None]


def build_store_runtime_builder(
    *,
    price_store_type: type[PriceStoreT],
    price_event_store_type: type[PriceEventStoreT],
) -> Callable[[ConfigT], price_platform.store_runtime.StoreRuntime[PriceStoreT, PriceEventStoreT]]:
    """ストア型から runtime builder を作る。"""
    return lambda config: price_platform.store_runtime.build_store_runtime_for(
        config,
        price_store_type=price_store_type,
        price_event_store_type=price_event_store_type,
    )


def build_service_builder(
    factories: ServiceFactories[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
) -> Callable[[ConfigT], price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]]:
    """サービス factory 群から service builder を作る。"""
    return lambda config: build_app_services(config, factories)


def build_standard_webapi_dependency_spec(
    *,
    extension_key: str,
    price_store_type: type[PriceStoreT],
    price_event_store_type: type[PriceEventStoreT],
    service_builder: Callable[
        [ConfigT],
        price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
    ],
) -> price_platform.webapp.WebApiDependencySpec[
    ConfigT,
    price_platform.store_runtime.StoreRuntime[PriceStoreT, PriceEventStoreT],
    price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
]:
    """標準的な Web API dependency spec を作る。"""
    return price_platform.webapp.WebApiDependencySpec(
        extension_key=extension_key,
        store_builder=build_store_runtime_builder(
            price_store_type=price_store_type,
            price_event_store_type=price_event_store_type,
        ),
        service_builder=service_builder,
    )


def build_standard_webapi_context(
    *,
    extension_key: str,
    price_store_type: type[PriceStoreT],
    price_event_store_type: type[PriceEventStoreT],
    service_builder: Callable[
        [ConfigT],
        price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
    ],
) -> price_platform.webapp.WebApiContext[
    ConfigT,
    price_platform.store_runtime.StoreRuntime[PriceStoreT, PriceEventStoreT],
    price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
]:
    """標準 spec と accessor 群をまとめた Web API context を作る。"""
    return price_platform.webapp.build_webapi_context(
        build_standard_webapi_dependency_spec(
            extension_key=extension_key,
            price_store_type=price_store_type,
            price_event_store_type=price_event_store_type,
            service_builder=service_builder,
        )
    )


def build_store_runtime(
    config: ConfigT,
    factories: StoreRuntimeFactories[ConfigT, PriceStoreT, PriceEventStoreT],
) -> price_platform.store_runtime.StoreRuntime[PriceStoreT, PriceEventStoreT]:
    """ストア系ファクトリーから型付き `StoreRuntime` を組み立てる。"""
    return price_platform.store_runtime.build_store_runtime(
        config,
        price_store_factory=factories.price_store_factory,
        price_event_store_factory=factories.price_event_store_factory,
    )


def build_app_services(
    config: ConfigT,
    factories: ServiceFactories[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
) -> price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]:
    """サービスファクトリーから `AppServices` を構築する。"""
    return price_platform.webapp.build_app_services(
        metrics_db_factory=lambda: factories.metrics_db_factory(config),
        client_metrics_db_factory=lambda: factories.client_metrics_db_factory(config),
        notification_store_factory=lambda: factories.notification_store_factory(config),
        webpush_store_factory=lambda: factories.webpush_store_factory(config),
    )
