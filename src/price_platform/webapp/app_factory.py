"""Application factory scaffolding for price-platform."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import flask
import flask_cors
import my_lib.webapp.config
import my_lib.webapp.event
import werkzeug.middleware.proxy_fix
import werkzeug.exceptions

from .cors import get_cors_origins
from .headers import CacheRule, apply_common_headers
from .request_context import SupportsRequestConnection, install_request_hooks


@dataclass(frozen=True)
class WebAppSettings:
    """Shared webapp settings."""

    app_name: str
    url_prefix: str
    external_url: str
    static_dir_path: Path | None = None
    cache_rules: tuple[CacheRule, ...] = field(default_factory=tuple)
    default_api_max_age: int = 600
    html_content_security_policy: str | None = None
    enable_proxy_fix: bool = True
    enable_hsts: bool = True


@dataclass(frozen=True)
class CommonRoutesSettings:
    """Common non-SEO routes shared by price applications."""

    url_prefix: str
    img_dir: Path
    flea_thumb_dir: Path


@dataclass(frozen=True)
class BlueprintRegistration:
    """Blueprint and target prefix pair."""

    blueprint: flask.Blueprint
    url_prefix: str | None = None


def configure_app(app: flask.Flask, settings: WebAppSettings) -> flask.Flask:
    """Apply shared webapp configuration to an existing Flask app."""
    if settings.enable_proxy_fix:
        app.wsgi_app = werkzeug.middleware.proxy_fix.ProxyFix(  # type: ignore[assignment]
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
            x_prefix=1,
        )

    flask_cors.CORS(app, origins=get_cors_origins(settings.external_url))

    if hasattr(app, "json") and hasattr(app.json, "compat"):
        app.json.compat = True  # type: ignore[attr-defined]

    @app.after_request
    def add_response_headers(response: flask.Response) -> flask.Response:
        return apply_common_headers(
            response,
            path=flask.request.path,
            api_prefix=f"{settings.url_prefix}/api/",
            cache_rules=settings.cache_rules,
            html_content_security_policy=settings.html_content_security_policy,
            default_api_max_age=settings.default_api_max_age,
            enable_hsts=settings.enable_hsts,
        )

    return app


def create_app(settings: WebAppSettings) -> flask.Flask:
    """Create a Flask app preconfigured with shared webapp behavior."""
    app = flask.Flask(settings.app_name)
    return configure_app(app, settings)


def create_platform_app(
    settings: WebAppSettings,
    *,
    connection_getter: Callable[[], SupportsRequestConnection],
    logger: logging.Logger | None = None,
) -> flask.Flask:
    """Create a shared price-platform Flask app with request hooks installed."""
    app = create_app(settings)
    install_request_hooks(
        app,
        api_prefix=f"{settings.url_prefix}/api/",
        connection_getter=connection_getter,
        logger=logger,
    )
    return app


def register_blueprints(app: flask.Flask, registrations: tuple[BlueprintRegistration, ...]) -> None:
    """Register multiple blueprints declaratively."""
    for registration in registrations:
        app.register_blueprint(registration.blueprint, url_prefix=registration.url_prefix)


def install_common_routes(
    app: flask.Flask,
    *,
    settings: CommonRoutesSettings,
    healthcheck: Callable[[], None],
    logger: logging.Logger | None = None,
) -> None:
    """Install shared health / SSE / static asset / error routes."""
    app_logger = logger or logging.getLogger(__name__)

    @app.route(f"{settings.url_prefix}/api/healthz")
    def healthz() -> tuple[flask.Response, int]:
        try:
            healthcheck()
            return flask.jsonify({"status": "ok"}), 200
        except sqlite3.Error as exc:
            app_logger.exception("ヘルスチェックに失敗しました: %s", exc)
            return flask.jsonify({"status": "error"}), 503

    app.register_blueprint(my_lib.webapp.event.blueprint, url_prefix=settings.url_prefix)

    @app.route(f"{settings.url_prefix}/img/<path:filepath>")
    def serve_image(filepath: str) -> flask.Response:
        response = flask.send_from_directory(settings.img_dir, filepath)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.route(f"{settings.url_prefix}/api/flea-thumb/<filename>")
    def serve_flea_thumb(filename: str) -> flask.Response | tuple[str, int]:
        if not settings.flea_thumb_dir.exists():
            return "Not Found", 404

        try:
            response = flask.send_from_directory(settings.flea_thumb_dir, filename)
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
            return response
        except (FileNotFoundError, OSError):
            return "Not Found", 404

    @app.errorhandler(404)
    def not_found(error: Exception) -> tuple[str, int]:
        _ = error
        return "Not Found", 404

    @app.errorhandler(500)
    def handle_internal_error(error: Exception) -> tuple[flask.Response, int]:
        app_logger.exception("Internal server error: %s", error)
        return flask.jsonify({"error": "Internal Server Error"}), 500

    @app.errorhandler(Exception)
    def handle_exception(error: Exception) -> flask.Response | tuple[flask.Response, int]:
        if isinstance(error, werkzeug.exceptions.HTTPException):
            return error.get_response()
        app_logger.exception("Unhandled exception: %s", error)
        return flask.jsonify({"error": "Internal Server Error"}), 500


def finalize_platform_app(
    app: flask.Flask,
    *,
    logger: logging.Logger | None = None,
    warmup: Callable[[], None] | None = None,
) -> None:
    """Run final shared steps after app-specific routes have been registered."""
    app_logger = logger or logging.getLogger(__name__)
    my_lib.webapp.config.show_handler_list(app)

    if warmup is None:
        return

    with app.app_context():
        app_logger.info("ウォームアップを開始します...")
        warmup()
        app_logger.info("ウォームアップ完了")
