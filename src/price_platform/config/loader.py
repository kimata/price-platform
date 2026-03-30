"""Configuration loading helpers for price-platform applications."""

from __future__ import annotations

import difflib
import logging
import os
from pathlib import Path
from typing import Any

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
)

logger = logging.getLogger(__name__)

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


def warn_unknown_keys(data: dict[str, Any], known_keys: set[str], section_name: str) -> None:
    """Warn about unknown keys in config data."""
    unknown = set(data.keys()) - known_keys
    for key in sorted(unknown):
        candidates = difflib.get_close_matches(key, known_keys, n=1, cutoff=0.6)
        hint = f" (did you mean '{candidates[0]}'?)" if candidates else ""
        logger.warning("Unknown key '%s' in %s section%s", key, section_name, hint)


def load_app_config(
    config_cls: type[AppConfig],
    *,
    env_var_name: str,
    default_liveness_file: Path,
    config_path: str | Path | None = None,
) -> AppConfig:
    """Load shared app config from YAML."""
    if config_path is None:
        config_path = os.environ.get(env_var_name, "config.yaml")

    try:
        data = my_lib.config.load(config_path)
    except my_lib.config.ConfigFileNotFoundError as exc:
        msg = f"Configuration file not found: {config_path}"
        raise FileNotFoundError(msg) from exc

    if not isinstance(data, dict):
        msg = "Configuration must be a mapping"
        raise ValueError(msg)

    base_dir = Path(config_path).absolute().parent
    return parse_app_config(
        config_cls,
        data,
        base_dir=base_dir,
        default_liveness_file=default_liveness_file,
    )


def parse_app_config(
    config_cls: type[AppConfig],
    data: dict[str, Any],
    *,
    default_liveness_file: Path,
    base_dir: Path | None = None,
) -> AppConfig:
    """Build shared app config from dict."""
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
        liveness=LivenessConfig.parse(data["liveness"], default_file=default_liveness_file, base_dir=base_dir),
        product_catalog_path=Path(data["product_catalog_path"]),
        cache=CacheConfig.parse(data["cache"], base_dir=base_dir),
        notification=NotificationConfig.parse(data.get("notification"), base_dir=base_dir),
        client_metrics=ClientMetricsConfig.parse(data.get("client_metrics"), base_dir=base_dir),
        _base_dir=base_dir,
    )
