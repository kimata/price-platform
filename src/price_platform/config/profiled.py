"""プロファイルベースの共有設定ヘルパー。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .loader import AppConfigSpec, load_app_config_for, parse_app_config_for
from .models import AppConfig


class ProfiledAppConfig(AppConfig):
    """AppConfig variant bound to a static AppConfigSpec profile."""

    PROFILE: ClassVar[AppConfigSpec]

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "ProfiledAppConfig":
        """Load configuration using the class profile."""
        return load_app_config_for(cls, cls.PROFILE, config_path=config_path)

    @classmethod
    def _from_dict(
        cls,
        data: dict[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> "ProfiledAppConfig":
        """Build configuration from a dictionary using the class profile."""
        return parse_app_config_for(cls, cls.PROFILE, data, base_dir=base_dir)
