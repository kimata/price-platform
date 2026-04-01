"""Schema path resolution for bundled SQLite schemas."""

from __future__ import annotations

from pathlib import Path

_BUNDLED_SCHEMA_DIR = Path(__file__).with_name("schema")


def bundled_schema_dir() -> Path:
    return _BUNDLED_SCHEMA_DIR


def resolve_schema_path(schema_name: str) -> Path:
    """Resolve the schema file path for a SQLite store."""

    bundled_path = _BUNDLED_SCHEMA_DIR / schema_name
    if bundled_path.exists():
        return bundled_path

    raise FileNotFoundError(f"Schema file not found: {schema_name}")
