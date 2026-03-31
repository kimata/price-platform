"""Service-layer helpers for metrics authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import jwt

from .secrets import FileSecretStore

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class MetricsAuthSettings:
    enabled: bool = False
    password_hash: str = ""
    jwt_secret_path: Path = Path("data/jwt_secret.key")
    jwt_expiry_hours: int = 24


class SupportsMetricsConfig(Protocol):
    metrics: Any


def issue_auth_token(settings: MetricsAuthSettings) -> str:
    secret = FileSecretStore(settings.jwt_secret_path).ensure()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.jwt_expiry_hours)
    payload = {"sub": "user", "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_auth_token(token: str, settings: MetricsAuthSettings) -> dict[str, Any] | None:
    try:
        secret = FileSecretStore(settings.jwt_secret_path).load()
    except FileNotFoundError:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return dict(payload)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def build_metrics_auth_settings_getter(
    *,
    config_getter: Callable[[], SupportsMetricsConfig],
) -> Callable[[], MetricsAuthSettings]:
    def settings_getter() -> MetricsAuthSettings:
        auth = config_getter().metrics.auth
        return MetricsAuthSettings(
            enabled=auth.enabled,
            password_hash=auth.password_hash,
            jwt_secret_path=auth.jwt_secret_path,
            jwt_expiry_hours=auth.jwt_expiry_hours,
        )

    return settings_getter
