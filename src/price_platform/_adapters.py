"""Private adapters that isolate direct runtime dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flask

from .platform import config as platform_config
from .platform import webapp as platform_webapp

ConfigFileNotFoundError = platform_config.ConfigFileNotFoundError
ConfigParseError = platform_config.ConfigParseError


def load_yaml_config(
    config_path: str | Path,
    schema_path: str | Path | None = None,
    *,
    include_base_dir: bool = True,
) -> Any:
    """Load YAML data through the current config adapter."""
    if schema_path is None:
        return platform_config.load_yaml(config_path)
    return platform_config.load_yaml(config_path, schema_path, include_base_dir=include_base_dir)


def get_event_blueprint() -> flask.Blueprint:
    """Return the shared SSE blueprint."""
    return platform_webapp.get_event_blueprint()


def show_handler_list(app: flask.Flask) -> None:
    """Log registered Flask handlers using the current webapp adapter."""
    platform_webapp.show_handler_list(app)


def notify_content_update() -> None:
    """Broadcast a content update event through the current event adapter."""
    platform_webapp.notify_content_update()
