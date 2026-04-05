"""Request-scoped context helpers for price-platform web applications."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Callable, Protocol

import flask


class SupportsRequestConnection(Protocol):
    """Protocol for stores that expose a request scoped connection context manager."""

    def request_connection(self) -> contextlib.AbstractContextManager[object]:
        """Return a context manager that binds a shared connection for the current request."""
        ...


def install_request_hooks(
    app: flask.Flask,
    *,
    api_prefix: str,
    connection_getter: Callable[[], SupportsRequestConnection],
    logger: logging.Logger | None = None,
    slow_request_threshold_ms: float = 10.0,
    timer_attr: str = "request_start",
    exit_stack_attr: str = "exit_stack",
) -> None:
    """Install request start/stop hooks for shared DB connection and timing logs."""
    app_logger = logger or logging.getLogger(__name__)

    @app.before_request
    def record_request_start() -> None:
        flask.g.__dict__[timer_attr] = time.monotonic()

        if flask.request.path.startswith(api_prefix):
            connection_owner: SupportsRequestConnection = connection_getter()
            stack = contextlib.ExitStack()
            stack.enter_context(connection_owner.request_connection())
            flask.g.__dict__[exit_stack_attr] = stack

    @app.teardown_request
    def close_shared_connection(exc: BaseException | None) -> None:
        _ = exc
        stack: contextlib.ExitStack | None = getattr(flask.g, exit_stack_attr, None)
        if stack is not None:
            stack.close()

    @app.after_request
    def log_request_duration(response: flask.Response) -> flask.Response:
        start = getattr(flask.g, timer_attr, None)
        if start is None:
            return response

        duration_ms = (time.monotonic() - start) * 1000
        if flask.request.path.startswith(api_prefix) and duration_ms >= slow_request_threshold_ms:
            app_logger.info("API %s %s %.0fms", flask.request.method, flask.request.path, duration_ms)
        return response
