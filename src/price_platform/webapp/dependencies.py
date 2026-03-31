"""Helpers for attaching typed dependency containers to Flask apps."""

from __future__ import annotations

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


@dataclass(frozen=True)
class AppServices(Generic[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]):
    """Optional long-lived services used by Web APIs."""

    metrics_db: MetricsDbT | None = None
    client_metrics_db: ClientMetricsDbT | None = None
    notification_store: NotificationStoreT | None = None
    webpush_store: WebPushStoreT | None = None


@dataclass(frozen=True)
class AppDependencies(Generic[ConfigT, StoresT, ServicesT]):
    """Common dependency container shape for Flask apps."""

    config: ConfigT
    stores: StoresT
    services: ServicesT


def build_app_services(
    *,
    metrics_db: MetricsDbT | None = None,
    client_metrics_db: ClientMetricsDbT | None = None,
    notification_store: NotificationStoreT | None = None,
    webpush_store: WebPushStoreT | None = None,
) -> AppServices[MetricsDbT, ClientMetricsDbT, NotificationStoreT, WebPushStoreT]:
    """Build an AppServices bundle."""
    return AppServices(
        metrics_db=metrics_db,
        client_metrics_db=client_metrics_db,
        notification_store=notification_store,
        webpush_store=webpush_store,
    )


def build_app_dependencies(
    config: ConfigT,
    stores: StoresT,
    services: ServicesT,
) -> AppDependencies[ConfigT, StoresT, ServicesT]:
    """Build a generic app dependency container."""
    return AppDependencies(config=config, stores=stores, services=services)


def install_dependencies(app: flask.Flask, extension_key: str, dependencies: DependenciesT) -> DependenciesT:
    """Attach a dependency container to ``app.extensions``."""
    app.extensions[extension_key] = dependencies
    return dependencies


def get_dependencies(extension_key: str) -> object:
    """Return a previously attached dependency container."""
    dependencies = flask.current_app.extensions.get(extension_key)
    if dependencies is None:
        raise RuntimeError(f"Dependencies not installed: {extension_key}")
    return dependencies


def get_typed_dependencies(extension_key: str, dependencies_type: type[DependenciesT]) -> DependenciesT:
    """Return a typed dependency container."""
    return cast(DependenciesT, get_dependencies(extension_key))
