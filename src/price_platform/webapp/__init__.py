"""Webapp helpers for price-platform."""

from .app_factory import (
    BlueprintRegistration,
    CommonRoutesSettings,
    WebAppSettings,
    configure_app,
    create_app,
    create_platform_app,
    finalize_platform_app,
    install_common_routes,
    register_blueprints,
)
from .cors import extract_origin, get_cors_origins, is_allowed_request_origin
from .headers import CacheRule, apply_common_headers
from .request_context import install_request_hooks

__all__ = [
    "BlueprintRegistration",
    "CacheRule",
    "CommonRoutesSettings",
    "WebAppSettings",
    "apply_common_headers",
    "configure_app",
    "create_app",
    "create_platform_app",
    "extract_origin",
    "finalize_platform_app",
    "install_common_routes",
    "get_cors_origins",
    "install_request_hooks",
    "is_allowed_request_origin",
    "register_blueprints",
]
