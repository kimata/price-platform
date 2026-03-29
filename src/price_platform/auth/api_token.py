"""API token helpers for price-platform applications."""

from __future__ import annotations

import functools
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import flask
import jwt

from ..webapp.cors import is_allowed_request_origin
from .secrets import FileSecretProvider

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class ApiTokenSettings:
    """Settings for short lived API tokens."""

    secret_path: str = "data/api_token_secret.key"
    expiry_sec: int = 180
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    ssr_internal_secret_env: str = "SSR_INTERNAL_SECRET"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_ssr_internal_secret(env_var: str) -> str | None:
    secret = os.environ.get(env_var, "")
    return secret or None


def generate_api_token(settings: ApiTokenSettings) -> str:
    """Generate a short lived API JWT."""
    secret = FileSecretProvider(settings.secret_path).get_secret()
    now = _utcnow()
    exp = now + timedelta(seconds=settings.expiry_sec)
    payload = {"type": "api", "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_api_token(token: str, settings: ApiTokenSettings) -> dict[str, Any] | None:
    """Verify a short lived API JWT."""
    secret = FileSecretProvider(settings.secret_path).get_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "api":
            return None
        return dict(payload)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def _is_same_origin_request(settings: ApiTokenSettings) -> bool:
    return is_allowed_request_origin(
        allowed_origins=settings.allowed_origins,
        origin=flask.request.headers.get("Origin"),
        referer=flask.request.headers.get("Referer"),
    )


def require_api_token(
    settings_getter: Callable[[], ApiTokenSettings],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Create a decorator that protects routes with short lived API tokens."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            settings = settings_getter()
            ssr_secret = _get_ssr_internal_secret(settings.ssr_internal_secret_env)
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
    """Create the API token blueprint."""
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
