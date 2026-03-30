"""Configuration loading helpers for price-platform applications."""

from __future__ import annotations

import difflib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import my_lib.config

from .models import (
    AppConfig,
    CacheConfig,
    ClientMetricsConfig,
    DatabaseConfig,
    LivenessConfig,
    MetricsConfig,
    NotificationConfig,
    ScrapeConfig,
    SeleniumConfig,
    StoreConfig,
    WebAppConfig,
    _resolve_path,
)

logger = logging.getLogger(__name__)
ConfigT = TypeVar("ConfigT", bound=AppConfig)

REQUIRED_SECTIONS = (
    "scrape",
    "store",
    "selenium",
    "database",
    "webapp",
    "metrics",
    "liveness",
    "product_catalog_path",
    "cache",
)
OPTIONAL_SECTIONS = ("notification", "client_metrics")


@dataclass(frozen=True)
class AppConfigSpec:
    """Application-specific knobs for loading shared config."""

    env_var_name: str
    default_liveness_file: Path


def warn_unknown_keys(data: dict[str, Any], known_keys: set[str], section_name: str) -> None:
    """Warn about unknown keys in config data."""
    unknown = set(data.keys()) - known_keys
    for key in sorted(unknown):
        candidates = difflib.get_close_matches(key, known_keys, n=1, cutoff=0.6)
        hint = f" (did you mean '{candidates[0]}'?)" if candidates else ""
        logger.warning("Unknown key '%s' in %s section%s", key, section_name, hint)


def load_app_config(
    config_cls: type[ConfigT],
    *,
    env_var_name: str,
    default_liveness_file: Path,
    config_path: str | Path | None = None,
) -> ConfigT:
    """Load shared app config from YAML."""
    return load_app_config_for(
        config_cls,
        AppConfigSpec(
            env_var_name=env_var_name,
            default_liveness_file=default_liveness_file,
        ),
        config_path=config_path,
    )


def load_app_config_for(
    config_cls: type[ConfigT],
    spec: AppConfigSpec,
    *,
    config_path: str | Path | None = None,
) -> ConfigT:
    """Load shared app config using an application-specific spec."""
    if config_path is None:
        config_path = os.environ.get(spec.env_var_name, "config.yaml")

    try:
        data = my_lib.config.load(config_path)
    except my_lib.config.ConfigFileNotFoundError as exc:
        msg = f"Configuration file not found: {config_path}"
        raise FileNotFoundError(msg) from exc

    if not isinstance(data, dict):
        msg = "Configuration must be a mapping"
        raise ValueError(msg)

    base_dir = Path(config_path).absolute().parent
    return parse_app_config_for(
        config_cls,
        spec,
        data,
        base_dir=base_dir,
    )


def parse_app_config(
    config_cls: type[ConfigT],
    data: dict[str, Any],
    *,
    default_liveness_file: Path,
    base_dir: Path | None = None,
) -> ConfigT:
    """Build shared app config from dict."""
    return parse_app_config_for(
        config_cls,
        AppConfigSpec(
            env_var_name="",
            default_liveness_file=default_liveness_file,
        ),
        data,
        base_dir=base_dir,
    )


def parse_app_config_for(
    config_cls: type[ConfigT],
    spec: AppConfigSpec,
    data: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> ConfigT:
    """Build shared app config from dict using an application-specific spec."""
    for section in REQUIRED_SECTIONS:
        if section not in data:
            msg = f"{section} configuration is required"
            raise ValueError(msg)

    known_sections = set(REQUIRED_SECTIONS) | set(OPTIONAL_SECTIONS)
    warn_unknown_keys(data, known_sections, "config")

    if base_dir is None:
        base_dir = Path.cwd()

    webapp = WebAppConfig.parse(data["webapp"], base_dir=base_dir)
    if not webapp.external_url:
        msg = "webapp.external_url is required for CORS configuration"
        raise ValueError(msg)

    return config_cls(
        scrape=ScrapeConfig.parse(data["scrape"]),
        store=StoreConfig.parse(data["store"]),
        selenium=SeleniumConfig.parse(data["selenium"], base_dir=base_dir),
        database=DatabaseConfig.parse(data["database"], base_dir=base_dir),
        webapp=webapp,
        metrics=MetricsConfig.parse(data["metrics"], base_dir=base_dir),
        liveness=LivenessConfig.parse(data["liveness"], default_file=spec.default_liveness_file, base_dir=base_dir),
        product_catalog_path=_resolve_path(data["product_catalog_path"], base_dir=base_dir),
        cache=CacheConfig.parse(data["cache"], base_dir=base_dir),
        notification=NotificationConfig.parse(data.get("notification"), base_dir=base_dir),
        client_metrics=ClientMetricsConfig.parse(data.get("client_metrics"), base_dir=base_dir),
        _base_dir=base_dir,
    )
