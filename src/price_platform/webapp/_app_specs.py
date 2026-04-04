"""Declarative configuration objects for shared Flask apps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import flask

from .headers import CacheRule


@dataclass(frozen=True)
class WebAppSettings:
    app_name: str
    url_prefix: str
    external_url: str
    static_dir_path: Path | None = None
    cache_rules: tuple[CacheRule, ...] = field(default_factory=tuple)
    default_api_max_age: int = 600
    html_content_security_policy: str | None = None
    enable_proxy_fix: bool = True
    enable_hsts: bool = True


@dataclass(frozen=True)
class CommonRoutesSettings:
    url_prefix: str
    img_dir: Path
    flea_thumb_dir: Path


@dataclass(frozen=True)
class BlueprintRegistration:
    blueprint: flask.Blueprint
    url_prefix: str | None = None


@dataclass(frozen=True)
class OptionalBlueprintRegistration:
    loader: Callable[[], flask.Blueprint]
    url_prefix: str | None = None
    missing_exceptions: tuple[type[Exception], ...] = (ImportError,)
    missing_message: str = "Optional blueprint not available, skipping registration"


@dataclass(frozen=True)
class PlatformAppSpec:
    settings: WebAppSettings
    common_routes: CommonRoutesSettings
    healthcheck: Callable[[], object]
    blueprints: tuple[BlueprintRegistration, ...] = field(default_factory=tuple)
    optional_blueprints: tuple[OptionalBlueprintRegistration, ...] = field(default_factory=tuple)
    route_installers: tuple[Callable[[flask.Flask], None], ...] = field(default_factory=tuple)
    warmup_steps: tuple[Callable[[], object], ...] = field(default_factory=tuple)
    warmup: Callable[[], None] | None = None


@dataclass(frozen=True)
class SeoRoutesSpec:
    url_prefix: str
    sitemap_builder: Callable[[], str]
    robots_builder: Callable[[], str]
    image_sitemap_builder: Callable[[], str] | None = None
    sitemap_cache_max_age: int = 3600
    robots_cache_max_age: int = 86400
    image_sitemap_cache_max_age: int = 3600
