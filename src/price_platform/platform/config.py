"""Adapters for configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import my_lib.platform.config

ConfigFileNotFoundError = my_lib.platform.config.ConfigFileNotFoundError
ConfigParseError = my_lib.platform.config.ConfigParseError


def load_yaml(
    config_path: str | Path,
    schema_path: str | Path | None = None,
    *,
    include_base_dir: bool = True,
) -> Any:
    if schema_path is None:
        return my_lib.platform.config.load(config_path)
    return my_lib.platform.config.load(config_path, schema_path, include_base_dir=include_base_dir)
