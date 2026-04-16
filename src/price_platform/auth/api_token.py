"""API token helpers for price-platform applications."""

from pathlib import Path

from ._api_token_flask import (
    ApiTokenFacade,
    build_api_token_facade,
    create_api_token_blueprint,
    require_api_token,
)
from ._api_token_service import (
    JWT_ALGORITHM,
    ApiTokenSettings,
    SupportsWebappConfig,
    build_api_token_settings_getter,
    generate_api_token,
    verify_api_token,
)

DEFAULT_API_TOKEN_EXPIRY_SEC = 180
DEFAULT_API_TOKEN_SECRET_PATH = Path("data/api_token_secret.key")


def build_standard_api_token_facade(
    *,
    config_getter,
    secret_path: Path = DEFAULT_API_TOKEN_SECRET_PATH,
    expiry_sec: int = DEFAULT_API_TOKEN_EXPIRY_SEC,
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET",
) -> ApiTokenFacade:
    """Build the conventional API token facade used by consumer apps."""
    return build_api_token_facade(
        config_getter=config_getter,
        secret_path=secret_path,
        expiry_sec=expiry_sec,
        ssr_internal_secret_env=ssr_internal_secret_env,
    )


__all__ = [
    "DEFAULT_API_TOKEN_EXPIRY_SEC",
    "DEFAULT_API_TOKEN_SECRET_PATH",
    "JWT_ALGORITHM",
    "ApiTokenFacade",
    "ApiTokenSettings",
    "SupportsWebappConfig",
    "build_api_token_facade",
    "build_api_token_settings_getter",
    "build_standard_api_token_facade",
    "create_api_token_blueprint",
    "generate_api_token",
    "require_api_token",
    "verify_api_token",
]
