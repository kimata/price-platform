"""Application factory scaffolding for price-platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import flask
import flask_cors
import werkzeug.middleware.proxy_fix

from .cors import get_cors_origins
from .headers import CacheRule, apply_common_headers


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
