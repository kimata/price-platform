"""各アプリ共通で使うランタイム構築ヘルパー。"""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import flask

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
ServiceT = TypeVar("ServiceT")


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


@dataclass(frozen=True)
class StandardWebApiAppDefinition:
    """共通 Flask アプリ骨格に渡す宣言的なアプリ定義。"""

    app_name: str
    url_prefix: str
    base_dir: Path
    cache_rules: tuple[price_platform.webapp.CacheRule, ...] = ()
    html_content_security_policy: str | None = None
    blueprints: tuple[price_platform.webapp.BlueprintRegistration, ...] = ()
    optional_blueprints: tuple[price_platform.webapp.OptionalBlueprintRegistration, ...] = ()
    route_installers: tuple[Callable[[flask.Flask], None], ...] = ()
    warmup_steps: tuple[Callable[[], object], ...] = ()
    flea_thumb_subdir: str = "fleama_thumb"


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


def build_optional_service_factory(
    *,
    enabled: Callable[[ConfigT], bool],
    path_getter: Callable[[ConfigT], Path],
    opener: Callable[[Path], ServiceT],
) -> Callable[[ConfigT], ServiceT | None]:
    """設定条件つきでサービスを開く factory を作る。"""

    def _factory(config: ConfigT) -> ServiceT | None:
        if not enabled(config):
            return None
        return opener(path_getter(config))

    return _factory


def safe_service_getter(getter: Callable[[], ServiceT]) -> Callable[[], ServiceT | None]:
    """未初期化 RuntimeError を握りつぶす getter を返す。"""

    def _get() -> ServiceT | None:
        try:
            return getter()
        except RuntimeError:
            return None

    return _get


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


def create_standard_webapi_app(
    config: ConfigT,
    *,
    definition: StandardWebApiAppDefinition,
    dependencies: price_platform.webapp.AppDependencies[ConfigT, StoresT, ServicesT],
    connection_getter: Callable[[], object],
    install_dependencies: Callable[
        [flask.Flask, price_platform.webapp.AppDependencies[ConfigT, StoresT, ServicesT]],
        None,
    ],
    logger: logging.Logger | None = None,
) -> flask.Flask:
    """共通骨格から標準 Web API アプリを組み立てる。"""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    external_url = getattr(getattr(config, "webapp"), "external_url", None)
    if external_url is None:
        msg = "Configuration error: webapp.external_url is required"
        raise ValueError(msg)

    spec = price_platform.webapp.create_standard_platform_spec(
        price_platform.webapp.StandardPlatformAppSpec(
            app_name=definition.app_name,
            url_prefix=definition.url_prefix,
            external_url=external_url,
            base_dir=definition.base_dir,
            flea_thumb_dir=getattr(config, "absolute_cache_path") / definition.flea_thumb_subdir,
            healthcheck=lambda: getattr(dependencies.stores, "price_store").get_last_update_time(),
            cache_rules=definition.cache_rules,
            html_content_security_policy=definition.html_content_security_policy,
            blueprints=definition.blueprints,
            optional_blueprints=definition.optional_blueprints,
            route_installers=definition.route_installers,
            warmup_steps=definition.warmup_steps,
        ),
    )

    app = price_platform.webapp.create_configured_platform_app(
        spec,
        connection_getter=connection_getter,
        logger=logger,
    )
    install_dependencies(app, dependencies)
    return app


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
