"""Helpers for attaching typed dependency containers to Flask apps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

import flask

DependenciesT = TypeVar("DependenciesT")
ConfigT = TypeVar("ConfigT")
StoresT = TypeVar("StoresT")


@dataclass(frozen=True)
class AppDependencies(Generic[ConfigT, StoresT]):
    """Common dependency container shape for Flask apps."""

    config: ConfigT
    stores: StoresT


def build_app_dependencies(config: ConfigT, stores: StoresT) -> AppDependencies[ConfigT, StoresT]:
    """Build a generic app dependency container."""
    return AppDependencies(config=config, stores=stores)


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
