"""Service-layer helpers for short-lived API tokens."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import jwt

from ..webapp.cors import get_cors_origins
from .secrets import FileSecretStore

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class ApiTokenSettings:
    secret_path: Path = Path("data/api_token_secret.key")
    expiry_sec: int = 180
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET"


class SupportsWebappConfig(Protocol):
    webapp: Any


def get_ssr_internal_secret(env_var: str) -> str | None:
    secret = os.environ.get(env_var, "")
    return secret or None


def generate_api_token(settings: ApiTokenSettings) -> str:
    secret = FileSecretStore(settings.secret_path).ensure()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=settings.expiry_sec)
    payload = {"type": "api", "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_api_token(token: str, settings: ApiTokenSettings) -> dict[str, Any] | None:
    try:
        secret = FileSecretStore(settings.secret_path).load()
    except FileNotFoundError:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "api":
            return None
        return dict(payload)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def build_api_token_settings_getter(
    *,
    config_getter: Callable[[], SupportsWebappConfig],
    secret_path: Path,
    expiry_sec: int = 180,
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET",
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
