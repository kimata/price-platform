"""Adapters for shared webapp helpers."""

from __future__ import annotations

import flask
import my_lib.webapp.config
import my_lib.webapp.event


def get_event_blueprint() -> flask.Blueprint:
    return my_lib.webapp.event.blueprint


def show_handler_list(app: flask.Flask) -> None:
    my_lib.webapp.config.show_handler_list(app)


def notify_content_update() -> None:
    my_lib.webapp.event.notify_event(my_lib.webapp.event.EVENT_TYPE.CONTENT)
