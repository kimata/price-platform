"""Webapp helpers for price-platform."""

from .app_factory import (
    BlueprintRegistration,
    CommonRoutesSettings,
    OptionalBlueprintRegistration,
    PlatformAppSpec,
    SeoRoutesSpec,
    WebAppSettings,
    configure_app,
    create_warmup,
    create_app,
    create_configured_platform_app,
    create_platform_app,
    finalize_platform_app,
    install_common_routes,
    install_seo_routes,
    notify_content_update,
    register_blueprints,
    register_optional_blueprints,
)
from .dependencies import (
    AppDependencies,
    AppServices,
    build_app_dependencies,
    build_app_services,
    get_dependencies,
    get_typed_dependencies,
    install_dependencies,
)
from .cors import extract_origin, get_cors_origins, is_allowed_request_origin
from .headers import CacheRule, apply_common_headers
from .request_context import install_request_hooks
from .runtime_memory_routes import install_runtime_memory_routes

__all__ = [
    "BlueprintRegistration",
    "CacheRule",
    "CommonRoutesSettings",
    "AppDependencies",
    "AppServices",
    "build_app_dependencies",
    "build_app_services",
    "get_dependencies",
    "get_typed_dependencies",
    "install_dependencies",
    "OptionalBlueprintRegistration",
    "PlatformAppSpec",
    "SeoRoutesSpec",
    "WebAppSettings",
    "apply_common_headers",
    "configure_app",
    "create_warmup",
    "create_app",
    "create_configured_platform_app",
    "create_platform_app",
    "extract_origin",
    "finalize_platform_app",
    "install_common_routes",
    "install_seo_routes",
    "notify_content_update",
    "get_cors_origins",
    "install_request_hooks",
    "install_runtime_memory_routes",
    "is_allowed_request_origin",
    "register_blueprints",
    "register_optional_blueprints",
]
