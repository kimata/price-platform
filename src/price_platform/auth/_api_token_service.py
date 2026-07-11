"""Service-layer helpers for short-lived API tokens."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from ..webapp.cors import get_cors_origins
from ._jwt_service import JWT_ALGORITHM, decode_token, encode_token

__all__ = ["JWT_ALGORITHM"]  # 公開 facade からの再エクスポート互換


@dataclass(frozen=True)
class ApiTokenSettings:
    secret_path: Path = Path("data/api_token_secret.key")
    expiry_sec: int = 180
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET"  # noqa: S105 - 環境変数名であり秘密ではない


class SupportsWebappConfig(Protocol):
    webapp: Any


def get_ssr_internal_secret(env_var: str) -> str | None:
    secret = os.environ.get(env_var, "")
    return secret or None


def generate_api_token(settings: ApiTokenSettings) -> str:
    return encode_token(
        settings.secret_path,
        claims={"type": "api"},
        lifetime=timedelta(seconds=settings.expiry_sec),
    )


def verify_api_token(token: str, settings: ApiTokenSettings) -> dict[str, Any] | None:
    return decode_token(settings.secret_path, token, expected_type="api")


def build_api_token_settings_getter(
    *,
    config_getter: Callable[[], SupportsWebappConfig],
    secret_path: Path,
    expiry_sec: int = 180,
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET",  # noqa: S107 - 環境変数名であり秘密ではない
) -> Callable[[], ApiTokenSettings]:
    def settings_getter() -> ApiTokenSettings:
        try:
            config = config_getter()
            external_url = config.webapp.external_url
            allowed_origins = tuple(get_cors_origins(external_url)) if external_url else ()
        except (FileNotFoundError, ValueError):
            allowed_origins = ()
        return ApiTokenSettings(
            secret_path=secret_path,
            expiry_sec=expiry_sec,
            allowed_origins=allowed_origins,
            ssr_internal_secret_env=ssr_internal_secret_env,
        )

    return settings_getter
