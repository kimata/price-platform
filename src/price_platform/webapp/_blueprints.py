"""Blueprint registration helpers for shared Flask apps."""

from __future__ import annotations

import logging

import flask

from ._app_specs import BlueprintRegistration, OptionalBlueprintRegistration


def register_blueprints(app: flask.Flask, registrations: tuple[BlueprintRegistration, ...]) -> None:
    for registration in registrations:
        app.register_blueprint(registration.blueprint, url_prefix=registration.url_prefix)


def register_optional_blueprints(
    app: flask.Flask,
    registrations: tuple[OptionalBlueprintRegistration, ...],
    *,
    logger: logging.Logger | None = None,
) -> None:
    app_logger = logger or logging.getLogger(__name__)
    for registration in registrations:
        try:
            blueprint = registration.loader()
        except registration.missing_exceptions:
            app_logger.info(registration.missing_message)
            continue
        app.register_blueprint(blueprint, url_prefix=registration.url_prefix)
