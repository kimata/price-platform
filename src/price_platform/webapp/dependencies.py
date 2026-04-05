"""型付き依存コンテナを Flask アプリへ接続するヘルパー。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

import flask

ConfigT = TypeVar("ConfigT")
StoresT = TypeVar("StoresT")
ServicesT = TypeVar("ServicesT")
DependenciesT = TypeVar("DependenciesT")
MetricsDbT = TypeVar("MetricsDbT")
ClientMetricsDbT = TypeVar("ClientMetricsDbT")
NotificationStoreT = TypeVar("NotificationStoreT")
WebPushStoreT = TypeVar("WebPushStoreT")
ServiceT = TypeVar("ServiceT")


def _get_request_service_cache() -> dict[str, object]:
    cache = getattr(flask.g, "_app_service_cache", None)
    if cache is None:
        cache = {}
        flask.g._app_service_cache = cache
    return cast(dict[str, object], cache)


def _resolve_service(
    name: str,
    service: ServiceT | None,
    factory: Callable[[], ServiceT | None] | None,
) -> ServiceT | None:
    if service is not None:
        return service
    if factory is None:
        return None
    if not flask.has_request_context():
        return factory()

    cache = _get_request_service_cache()
    if name not in cache:
        cache[name] = factory()
    return cast(ServiceT | None, cache[name])


def _validate_service_source(
    name: str, service: object | None, factory: Callable[[], object | None] | None
) -> None:
    if service is not None and factory is not None:
        raise ValueError(f"{name} and {name}_factory cannot both be provided")


@dataclass(frozen=True)
class AppServices(Generic[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]):
    """Optional service accessors used by Web APIs."""

    _metrics_db: MetricsDbT | None = None
    _metrics_db_factory: Callable[[], MetricsDbT | None] | None = None
    _client_metrics_db: ClientMetricsDbT | None = None
    _client_metrics_db_factory: Callable[[], ClientMetricsDbT | None] | None = None
    _notification_store: NotificationStoreT | None = None
    _notification_store_factory: Callable[[], NotificationStoreT | None] | None = None
    _webpush_store: WebPushStoreT | None = None
    _webpush_store_factory: Callable[[], WebPushStoreT | None] | None = None

    @property
    def metrics_db(self) -> MetricsDbT | None:
        return _resolve_service("metrics_db", self._metrics_db, self._metrics_db_factory)

    @property
    def client_metrics_db(self) -> ClientMetricsDbT | None:
        return _resolve_service(
            "client_metrics_db",
            self._client_metrics_db,
            self._client_metrics_db_factory,
        )

    @property
    def notification_store(self) -> NotificationStoreT | None:
        return _resolve_service(
            "notification_store",
            self._notification_store,
            self._notification_store_factory,
        )

    @property
    def webpush_store(self) -> WebPushStoreT | None:
        return _resolve_service("webpush_store", self._webpush_store, self._webpush_store_factory)


@dataclass(frozen=True)
class AppDependencies(Generic[ConfigT, StoresT, ServicesT]):
    """Common dependency container shape for Flask apps."""

    config: ConfigT
    stores: StoresT
    services: ServicesT


@dataclass(frozen=True)
class WebApiDependencySpec(Generic[ConfigT, StoresT, ServicesT]):
    """Web API 依存構成を宣言的に表す spec。"""

    extension_key: str
    store_builder: Callable[[ConfigT], StoresT]
    service_builder: Callable[[ConfigT], ServicesT]


def build_app_services(
    *,
    metrics_db: MetricsDbT | None = None,
    metrics_db_factory: Callable[[], MetricsDbT | None] | None = None,
    client_metrics_db: ClientMetricsDbT | None = None,
    client_metrics_db_factory: Callable[[], ClientMetricsDbT | None] | None = None,
    notification_store: NotificationStoreT | None = None,
    notification_store_factory: Callable[[], NotificationStoreT | None] | None = None,
    webpush_store: WebPushStoreT | None = None,
    webpush_store_factory: Callable[[], WebPushStoreT | None] | None = None,
) -> AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]:
    """Build an AppServices bundle."""
    _validate_service_source("metrics_db", metrics_db, metrics_db_factory)
    _validate_service_source("client_metrics_db", client_metrics_db, client_metrics_db_factory)
    _validate_service_source("notification_store", notification_store, notification_store_factory)
    _validate_service_source("webpush_store", webpush_store, webpush_store_factory)

    return AppServices(
        _metrics_db=metrics_db,
        _metrics_db_factory=metrics_db_factory,
        _client_metrics_db=client_metrics_db,
        _client_metrics_db_factory=client_metrics_db_factory,
        _notification_store=notification_store,
        _notification_store_factory=notification_store_factory,
        _webpush_store=webpush_store,
        _webpush_store_factory=webpush_store_factory,
    )


def build_app_dependencies(
    config: ConfigT,
    stores: StoresT,
    services: ServicesT,
) -> AppDependencies[ConfigT, StoresT, ServicesT]:
    """Build a generic app dependency container."""
    return AppDependencies(config=config, stores=stores, services=services)


def build_webapi_dependencies(
    config: ConfigT,
    spec: WebApiDependencySpec[ConfigT, StoresT, ServicesT],
) -> AppDependencies[ConfigT, StoresT, ServicesT]:
    """spec に基づいて Web API 用依存コンテナを構築する。"""
    return build_app_dependencies(
        config=config,
        stores=spec.store_builder(config),
        services=spec.service_builder(config),
    )


def install_dependencies(app: flask.Flask, extension_key: str, dependencies: DependenciesT) -> DependenciesT:
    """Attach a dependency container to ``app.extensions``."""
    app.extensions[extension_key] = dependencies
    return dependencies


def install_webapi_dependencies(
    app: flask.Flask,
    spec: WebApiDependencySpec[ConfigT, StoresT, ServicesT],
    dependencies: AppDependencies[ConfigT, StoresT, ServicesT],
) -> AppDependencies[ConfigT, StoresT, ServicesT]:
    """Web API 用依存コンテナを app.extensions へ登録する。"""
    return install_dependencies(app, spec.extension_key, dependencies)


def get_dependencies(extension_key: str) -> object:
    """Return a previously attached dependency container."""
    dependencies = flask.current_app.extensions.get(extension_key)
    if dependencies is None:
        raise RuntimeError(f"Dependencies not installed: {extension_key}")
    return dependencies


def get_typed_dependencies(extension_key: str, dependencies_type: type[DependenciesT]) -> DependenciesT:
    """Return a typed dependency container."""
    return cast(DependenciesT, get_dependencies(extension_key))


def get_webapi_dependencies(
    spec: WebApiDependencySpec[ConfigT, StoresT, ServicesT],
) -> AppDependencies[ConfigT, StoresT, ServicesT]:
    """spec に対応する Web API 依存コンテナを返す。"""
    return get_typed_dependencies(spec.extension_key, AppDependencies)


def get_webapi_config(spec: WebApiDependencySpec[ConfigT, StoresT, ServicesT]) -> ConfigT:
    """spec に対応するアプリ設定を返す。"""
    return get_webapi_dependencies(spec).config


def get_webapi_services(spec: WebApiDependencySpec[ConfigT, StoresT, ServicesT]) -> ServicesT:
    """spec に対応するサービス束を返す。"""
    return get_webapi_dependencies(spec).services
