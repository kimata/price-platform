"""Private adapters that isolate direct my_lib dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flask
import my_lib.config
import my_lib.webapp.config
import my_lib.webapp.event

ConfigFileNotFoundError = my_lib.config.ConfigFileNotFoundError
ConfigParseError = my_lib.config.ConfigParseError


def load_yaml_config(
    config_path: str | Path,
    schema_path: str | Path | None = None,
    *,
    include_base_dir: bool = True,
) -> Any:
    """Load YAML data through the current my_lib adapter."""
    if schema_path is None:
        return my_lib.config.load(config_path)
    return my_lib.config.load(config_path, schema_path, include_base_dir=include_base_dir)


def get_event_blueprint() -> flask.Blueprint:
    """Return the shared SSE blueprint."""
    return my_lib.webapp.event.blueprint


def show_handler_list(app: flask.Flask) -> None:
    """Log registered Flask handlers using the current webapp adapter."""
    my_lib.webapp.config.show_handler_list(app)


def notify_content_update() -> None:
    """Broadcast a content update event through the current event adapter."""
    my_lib.webapp.event.notify_event(my_lib.webapp.event.EVENT_TYPE.CONTENT)
