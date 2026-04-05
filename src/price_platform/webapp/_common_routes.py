"""Shared non-SEO route installers for platform Flask apps."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

import flask
import price_platform._adapters
import werkzeug.exceptions

from ._app_specs import CommonRoutesSettings


def install_common_routes(
    app: flask.Flask,
    *,
    settings: CommonRoutesSettings,
    healthcheck: Callable[[], object],
    logger: logging.Logger | None = None,
) -> None:
    app_logger = logger or logging.getLogger(__name__)

    @app.route(f"{settings.url_prefix}/api/healthz")
    def healthz() -> tuple[flask.Response, int]:
        try:
            healthcheck()
            return flask.jsonify({"status": "ok"}), 200
        except sqlite3.Error as exc:
            app_logger.exception("ヘルスチェックに失敗しました: %s", exc)
            return flask.jsonify({"status": "error"}), 503

    app.register_blueprint(price_platform._adapters.get_event_blueprint(), url_prefix=settings.url_prefix)

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
            return flask.make_response(error.get_response())
        app_logger.exception("Unhandled exception: %s", error)
        return flask.jsonify({"error": "Internal Server Error"}), 500


def finalize_platform_app(
    app: flask.Flask,
    *,
    logger: logging.Logger | None = None,
    warmup: Callable[[], None] | None = None,
) -> None:
    app_logger = logger or logging.getLogger(__name__)
    price_platform._adapters.show_handler_list(app)

    if warmup is None:
        return

    with app.app_context():
        app_logger.info("ウォームアップを開始します...")
        warmup()
        app_logger.info("ウォームアップ完了")


def notify_content_update() -> None:
    price_platform._adapters.notify_content_update()
