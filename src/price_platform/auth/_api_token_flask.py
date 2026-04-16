"""Flask adapter for API token helpers."""

from __future__ import annotations

import functools
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import flask

from ..webapp.cors import is_allowed_request_origin
from ._api_token_service import (
    ApiTokenSettings,
    SupportsWebappConfig,
    build_api_token_settings_getter,
    generate_api_token,
    get_ssr_internal_secret,
    verify_api_token,
)


@dataclass(frozen=True)
class ApiTokenFacade:
    settings_getter: Callable[[], ApiTokenSettings]
    generate_api_token: Callable[[], str]
    verify_api_token: Callable[[str], dict[str, Any] | None]
    require_api_token: Callable[[Callable[..., Any]], Callable[..., Any]]
    blueprint: flask.Blueprint


def _is_same_origin_request(settings: ApiTokenSettings) -> bool:
    return is_allowed_request_origin(
        allowed_origins=settings.allowed_origins,
        origin=flask.request.headers.get("Origin"),
        referer=flask.request.headers.get("Referer"),
    )


def require_api_token(
    settings_getter: Callable[[], ApiTokenSettings],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            settings = settings_getter()
            ssr_secret = get_ssr_internal_secret(settings.ssr_internal_secret_env)
            if ssr_secret:
                header = flask.request.headers.get("X-SSR-Internal")
                if header and secrets.compare_digest(header, ssr_secret):
                    return func(*args, **kwargs)

            token = flask.request.headers.get("X-Api-Token")
            if not token:
                return flask.jsonify({"error": "API token required", "code": "API_TOKEN_REQUIRED"}), 401

            payload = verify_api_token(token, settings)
            if payload is None:
                return flask.jsonify({"error": "Invalid or expired API token", "code": "API_TOKEN_INVALID"}), 401

            return func(*args, **kwargs)

        return wrapped

    return decorator


def create_api_token_blueprint(
    *,
    settings_getter: Callable[[], ApiTokenSettings],
) -> flask.Blueprint:
    blueprint = flask.Blueprint("api_token", __name__)

    @blueprint.route("/token", methods=["GET"])
    def get_token() -> tuple[flask.Response, int]:
        settings = settings_getter()
        if not _is_same_origin_request(settings):
            return flask.jsonify({"error": "Invalid request", "code": "INVALID_REQUEST"}), 403
        token = generate_api_token(settings)
        return flask.jsonify({"token": token, "expires_in": settings.expiry_sec}), 200

    @blueprint.route("/token/refresh", methods=["POST"])
    def refresh_token() -> tuple[flask.Response, int]:
        settings = settings_getter()
        if not _is_same_origin_request(settings):
            return flask.jsonify({"error": "Invalid request", "code": "INVALID_REQUEST"}), 403

        current_token = flask.request.headers.get("X-Api-Token")
        if current_token:
            verify_api_token(current_token, settings)

        token = generate_api_token(settings)
        return flask.jsonify({"token": token, "expires_in": settings.expiry_sec}), 200

    return blueprint


def build_api_token_facade(
    *,
    config_getter: Callable[[], SupportsWebappConfig],
    secret_path: Path,
    expiry_sec: int = 180,
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET",
) -> ApiTokenFacade:
    settings_getter = build_api_token_settings_getter(
        config_getter=config_getter,
        secret_path=secret_path,
        expiry_sec=expiry_sec,
        ssr_internal_secret_env=ssr_internal_secret_env,
    )

    def generate_bound_token() -> str:
        return generate_api_token(settings_getter())

    def verify_bound_token(token: str) -> dict[str, Any] | None:
        return verify_api_token(token, settings_getter())

    return ApiTokenFacade(
        settings_getter=settings_getter,
        generate_api_token=generate_bound_token,
        verify_api_token=verify_bound_token,
        require_api_token=require_api_token(settings_getter),
        blueprint=create_api_token_blueprint(settings_getter=settings_getter),
    )
