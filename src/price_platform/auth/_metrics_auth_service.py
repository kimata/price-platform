"""Service-layer helpers for metrics authentication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from ._jwt_service import JWT_ALGORITHM, decode_token, encode_token

__all__ = ["JWT_ALGORITHM"]  # 公開 facade からの再エクスポート互換


@dataclass(frozen=True)
class MetricsAuthSettings:
    enabled: bool = False
    password_hash: str = ""
    jwt_secret_path: Path = Path("data/jwt_secret.key")
    jwt_expiry_hours: int = 24


class SupportsMetricsConfig(Protocol):
    metrics: Any


def issue_auth_token(settings: MetricsAuthSettings) -> str:
    return encode_token(
        settings.jwt_secret_path,
        claims={"sub": "user"},
        lifetime=timedelta(hours=settings.jwt_expiry_hours),
    )


def verify_auth_token(token: str, settings: MetricsAuthSettings) -> dict[str, Any] | None:
    return decode_token(settings.jwt_secret_path, token)


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
