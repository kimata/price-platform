"""Metrics authentication helpers for price-platform applications."""

from ._metrics_auth_flask import (
    MetricsAuthFacade,
    build_metrics_auth_facade,
    create_metrics_auth_blueprint,
    require_auth,
)
from ._metrics_auth_service import (
    JWT_ALGORITHM,
    MetricsAuthSettings,
    SupportsMetricsConfig,
    build_metrics_auth_settings_getter,
    issue_auth_token,
    verify_auth_token,
)
from .rate_limiter import InMemoryRateLimiter


def build_standard_metrics_auth_facade(
    *,
    config_getter,
    limiter: InMemoryRateLimiter | None = None,
) -> MetricsAuthFacade:
    """Build the conventional metrics auth facade used by consumer apps."""
    return build_metrics_auth_facade(
        config_getter=config_getter,
        limiter=limiter,
    )

__all__ = [
    "JWT_ALGORITHM",
    "MetricsAuthFacade",
    "MetricsAuthSettings",
    "build_standard_metrics_auth_facade",
    "SupportsMetricsConfig",
    "build_metrics_auth_facade",
    "build_metrics_auth_settings_getter",
    "create_metrics_auth_blueprint",
    "issue_auth_token",
    "require_auth",
    "verify_auth_token",
]
