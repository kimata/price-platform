"""各アプリ共通で使うランタイム構築ヘルパー。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

import flask

import price_platform.store_runtime
import price_platform.webapp
from price_platform.identity import AppIdentity

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

COMMON_HTML_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com "
    "https://b.st-hatena.com https://bookmark.hatenaapis.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://www.google-analytics.com https://region1.google-analytics.com; "
    "frame-ancestors 'none';"
)


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

    @classmethod
    def from_identity(
        cls,
        identity: AppIdentity,
        *,
        base_dir: Path,
        cache_rules: tuple[price_platform.webapp.CacheRule, ...] = (),
        html_content_security_policy: str | None = None,
        blueprints: tuple[price_platform.webapp.BlueprintRegistration, ...] = (),
        optional_blueprints: tuple[price_platform.webapp.OptionalBlueprintRegistration, ...] = (),
        route_installers: tuple[Callable[[flask.Flask], None], ...] = (),
        warmup_steps: tuple[Callable[[], object], ...] = (),
    ) -> StandardWebApiAppDefinition:
        return cls(
            app_name=identity.resolved_flask_app_name,
            url_prefix=identity.url_prefix,
            base_dir=base_dir,
            cache_rules=cache_rules,
            html_content_security_policy=html_content_security_policy,
            blueprints=blueprints,
            optional_blueprints=optional_blueprints,
            route_installers=route_installers,
            warmup_steps=warmup_steps,
            flea_thumb_subdir=identity.flea_thumb_subdir,
        )


def _resolve_extension_key(*, extension_key: str | None, identity: AppIdentity | None) -> str:
    if extension_key is not None and identity is not None:
        msg = "extension_key and identity cannot both be provided"
        raise ValueError(msg)
    if identity is not None:
        return identity.extension_key
    if extension_key is None:
        msg = "extension_key or identity is required"
        raise ValueError(msg)
    return extension_key


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


def build_standard_service_builder(
    factories: ServiceFactories[ConfigT, MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT],
) -> Callable[[ConfigT], price_platform.webapp.AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]]:
    """標準 Web API 向け service builder を返す。"""
    return build_service_builder(factories)


def build_standard_webapi_dependency_spec(
    *,
    extension_key: str | None = None,
    identity: AppIdentity | None = None,
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
        extension_key=_resolve_extension_key(extension_key=extension_key, identity=identity),
        store_builder=build_store_runtime_builder(
            price_store_type=price_store_type,
            price_event_store_type=price_event_store_type,
        ),
        service_builder=service_builder,
    )


def build_standard_webapi_context(
    *,
    extension_key: str | None = None,
    identity: AppIdentity | None = None,
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
            identity=identity,
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
    connection_getter: Callable[[], price_platform.webapp.SupportsRequestConnection],
    install_dependencies: Callable[
        [flask.Flask, price_platform.webapp.AppDependencies[ConfigT, StoresT, ServicesT]],
        object,
    ],
    logger: logging.Logger | None = None,
) -> flask.Flask:
    """共通骨格から標準 Web API アプリを組み立てる。"""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    external_url = getattr(getattr(config, "webapp"), "external_url", None)  # noqa: B009
    if external_url is None:
        msg = "Configuration error: webapp.external_url is required"
        raise ValueError(msg)

    spec = price_platform.webapp.create_standard_platform_spec(
        price_platform.webapp.StandardPlatformAppSpec(
            app_name=definition.app_name,
            url_prefix=definition.url_prefix,
            external_url=external_url,
            base_dir=definition.base_dir,
            flea_thumb_dir=getattr(config, "absolute_cache_path") / definition.flea_thumb_subdir,  # noqa: B009
            healthcheck=lambda: getattr(dependencies.stores, "price_store").get_last_update_time(),  # noqa: B009
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


def create_standard_seo_route_installer(
    *,
    url_prefix: str,
    sitemap_builder: Callable[[], str],
    robots_builder: Callable[[], str],
    image_sitemap_builder: Callable[[], str] | None = None,
) -> Callable[[flask.Flask], None]:
    """Build a route installer for the standard SEO endpoints."""

    def install_routes(app: flask.Flask) -> None:
        price_platform.webapp.install_seo_routes(
            app,
            price_platform.webapp.SeoRoutesSpec(
                url_prefix=url_prefix,
                sitemap_builder=sitemap_builder,
                robots_builder=robots_builder,
                image_sitemap_builder=image_sitemap_builder,
            ),
        )

    return install_routes


def build_optional_webpush_blueprint_registration(
    *,
    url_prefix: str,
    loader: Callable[[], flask.Blueprint],
    missing_message: str = "WebPush API module not available, skipping registration",
) -> price_platform.webapp.OptionalBlueprintRegistration:
    """Build the canonical optional WebPush blueprint registration."""
    return price_platform.webapp.OptionalBlueprintRegistration(
        loader=loader,
        url_prefix=f"{url_prefix}/api/webpush",
        missing_message=missing_message,
    )


def notify_price_update(product_id: str) -> None:
    """Emit the shared content update event after a price change."""
    _ = product_id
    price_platform.webapp.notify_content_update()


def notify_scrape_complete() -> None:
    """Emit the shared content update event after a scrape completes."""
    price_platform.webapp.notify_content_update()


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
