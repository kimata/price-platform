"""Application factory scaffolding for price-platform."""

from __future__ import annotations

import logging
from collections.abc import Callable

import flask
import flask_cors
import werkzeug.middleware.proxy_fix

from ._app_specs import (
    BlueprintRegistration,
    CommonRoutesSettings,
    OptionalBlueprintRegistration,
    PlatformAppSpec,
    SeoRoutesSpec,
    WebAppSettings,
)
from ._blueprints import register_blueprints, register_optional_blueprints
from ._common_routes import finalize_platform_app, install_common_routes, notify_content_update
from ._seo_routes import install_seo_routes
from .cors import get_cors_origins
from .headers import apply_common_headers
from .request_context import SupportsRequestConnection, install_request_hooks


def configure_app(app: flask.Flask, settings: WebAppSettings) -> flask.Flask:
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
    app = flask.Flask(settings.app_name)
    return configure_app(app, settings)


def create_platform_app(
    settings: WebAppSettings,
    *,
    connection_getter: Callable[[], SupportsRequestConnection],
    logger: logging.Logger | None = None,
) -> flask.Flask:
    app = create_app(settings)
    install_request_hooks(
        app,
        api_prefix=f"{settings.url_prefix}/api/",
        connection_getter=connection_getter,
        logger=logger,
    )
    return app


def create_configured_platform_app(
    spec: PlatformAppSpec,
    *,
    connection_getter: Callable[[], SupportsRequestConnection],
    logger: logging.Logger | None = None,
) -> flask.Flask:
    app = create_platform_app(
        spec.settings,
        connection_getter=connection_getter,
        logger=logger,
    )
    install_common_routes(
        app,
        settings=spec.common_routes,
        healthcheck=spec.healthcheck,
        logger=logger,
    )
    register_blueprints(app, spec.blueprints)
    register_optional_blueprints(app, spec.optional_blueprints, logger=logger)
    for installer in spec.route_installers:
        installer(app)
    finalize_platform_app(app, logger=logger, warmup=spec.warmup)
    return app


def create_warmup(*steps: Callable[[], object]) -> Callable[[], None]:
    def warmup() -> None:
        for step in steps:
            step()

    return warmup
