"""Stable identity metadata for consumer applications."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppIdentity:
    """Declarative identity for a consumer application."""

    app_slug: str
    python_package: str
    url_prefix: str
    config_env_var: str
    default_liveness_file: Path
    flask_app_name: str | None = None
    flea_thumb_subdir: str = "fleama_thumb"

    @property
    def extension_key(self) -> str:
        return f"{self.python_package}.webapi.dependencies"

    @property
    def resolved_flask_app_name(self) -> str:
        return self.flask_app_name or f"{self.python_package}_webui"
