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

__all__ = [
    "JWT_ALGORITHM",
    "MetricsAuthFacade",
    "MetricsAuthSettings",
    "SupportsMetricsConfig",
    "build_metrics_auth_facade",
    "build_metrics_auth_settings_getter",
    "create_metrics_auth_blueprint",
    "issue_auth_token",
    "require_auth",
    "verify_auth_token",
]
