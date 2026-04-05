"""プロファイルベースの共有設定ヘルパー。"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Callable, ClassVar, Self, cast

from price_platform.identity import AppIdentity

from .loader import AppConfigSpec, load_app_config_for, parse_app_config_for
from .models import AppConfig


class ProfiledAppConfig(AppConfig):
    """AppConfig variant bound to a static AppConfigSpec profile."""

    PROFILE: ClassVar[AppConfigSpec]

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Self:
        """Load configuration using the class profile."""
        return load_app_config_for(cls, cls.PROFILE, config_path=config_path)

    @classmethod
    def _from_dict(
        cls,
        data: dict[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> Self:
        """Build configuration from a dictionary using the class profile."""
        return parse_app_config_for(cls, cls.PROFILE, data, base_dir=base_dir)


def create_profiled_app_config(
    identity: AppIdentity,
    *,
    class_name: str = "Config",
) -> type[ProfiledAppConfig]:
    """Create a ``ProfiledAppConfig`` subclass bound to an app identity."""
    config_cls = type(
        class_name,
        (ProfiledAppConfig,),
        {
            "__module__": __name__,
            "PROFILE": AppConfigSpec(
                env_var_name=identity.config_env_var,
                default_liveness_file=identity.default_liveness_file,
            ),
        },
    )
    return cast(type[ProfiledAppConfig], config_cls)


def build_cached_config_loader(config_cls: type[ProfiledAppConfig]) -> Callable[[], ProfiledAppConfig]:
    """Build a cached global config loader."""

    @functools.cache
    def get_config() -> ProfiledAppConfig:
        return config_cls.load()

    return get_config
