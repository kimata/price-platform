"""Flask adapter for metrics authentication."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Callable

import flask

from ._metrics_auth_service import (
    MetricsAuthSettings,
    SupportsMetricsConfig,
    build_metrics_auth_settings_getter,
    issue_auth_token,
    verify_auth_token,
)
from .password_hash import verify_password
from .rate_limiter import InMemoryRateLimiter


@dataclass(frozen=True)
class MetricsAuthFacade:
    settings_getter: Callable[[], MetricsAuthSettings]
    require_auth: Callable[[Callable[..., Any]], Callable[..., Any]]
    blueprint: flask.Blueprint


def _get_client_ip() -> str:
    return flask.request.remote_addr or "unknown"


def require_auth(settings_getter: Callable[[], MetricsAuthSettings]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            settings = settings_getter()
            if not settings.enabled:
                return func(*args, **kwargs)

            auth_header = flask.request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return flask.jsonify({"error": "Authentication required", "code": "AUTH_REQUIRED"}), 401

            payload = verify_auth_token(auth_header[7:], settings)
            if payload is None:
                return flask.jsonify({"error": "Invalid or expired token", "code": "TOKEN_INVALID"}), 401

            flask.g.auth_user = payload.get("sub")
            return func(*args, **kwargs)

        return wrapped

    return decorator


def create_metrics_auth_blueprint(
    *,
    settings_getter: Callable[[], MetricsAuthSettings],
    limiter: InMemoryRateLimiter | None = None,
) -> flask.Blueprint:
    blueprint = flask.Blueprint("metrics_auth", __name__)
    rate_limiter = limiter or InMemoryRateLimiter()

    @blueprint.route("/login", methods=["POST"])
    def login() -> tuple[flask.Response, int]:
        settings = settings_getter()
        if not settings.enabled:
            return flask.jsonify({"error": "Authentication is disabled", "code": "AUTH_DISABLED"}), 400

        client_ip = _get_client_ip()
        if rate_limiter.is_locked_out(client_ip):
            remaining = rate_limiter.get_lockout_remaining_sec(client_ip)
            return flask.jsonify(
                {
                    "error": f"Too many failed attempts. Try again in {remaining // 60} minutes.",
                    "code": "RATE_LIMITED",
                    "lockout_remaining_sec": remaining,
                }
            ), 429

        data = flask.request.get_json()
        if not isinstance(data, dict):
            return flask.jsonify({"error": "Request body required", "code": "INVALID_REQUEST"}), 400

        input_password = str(data.get("password", ""))
        if not settings.password_hash:
            return flask.jsonify({"error": "Authentication not configured", "code": "NOT_CONFIGURED"}), 500

        if not verify_password(input_password, settings.password_hash):
            locked_out = rate_limiter.record_failure(client_ip)
            if locked_out:
                remaining = rate_limiter.get_lockout_remaining_sec(client_ip)
                return flask.jsonify(
                    {
                        "error": f"Too many failed attempts. Locked out for {remaining // 60} minutes.",
                        "code": "RATE_LIMITED",
                        "lockout_remaining_sec": remaining,
                    }
                ), 429
            return flask.jsonify({"error": "Invalid credentials", "code": "INVALID_CREDENTIALS"}), 401

        rate_limiter.clear_failures(client_ip)
        token = issue_auth_token(settings)
        return flask.jsonify({"token": token, "expires_in": settings.jwt_expiry_hours * 3600}), 200

    @blueprint.route("/check", methods=["GET"])
    def check() -> tuple[flask.Response, int]:
        settings = settings_getter()
        if not settings.enabled:
            return flask.jsonify({"authenticated": True, "auth_enabled": False}), 200

        auth_header = flask.request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return flask.jsonify({"authenticated": False, "auth_enabled": True}), 200

        payload = verify_auth_token(auth_header[7:], settings)
        if payload is None:
            return flask.jsonify(
                {"authenticated": False, "auth_enabled": True, "error": "Invalid or expired token"}
            ), 200

        return flask.jsonify({"authenticated": True, "auth_enabled": True}), 200

    @blueprint.route("/logout", methods=["POST"])
    def logout() -> tuple[flask.Response, int]:
        return flask.jsonify({"success": True}), 200

    return blueprint


def build_metrics_auth_facade(
    *,
    config_getter: Callable[[], SupportsMetricsConfig],
    limiter: InMemoryRateLimiter | None = None,
) -> MetricsAuthFacade:
    settings_getter = build_metrics_auth_settings_getter(config_getter=config_getter)
    return MetricsAuthFacade(
        settings_getter=settings_getter,
        require_auth=require_auth(settings_getter),
        blueprint=create_metrics_auth_blueprint(settings_getter=settings_getter, limiter=limiter),
    )
