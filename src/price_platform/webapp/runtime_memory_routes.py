"""Route helpers for runtime memory metrics."""

from __future__ import annotations

import logging
from collections.abc import Callable

import flask

from price_platform.managers.pod_memory_tracker import MemorySeriesSnapshot, PodMemoryTracker
from price_platform.memory_svg import generate_memory_usage_svg


def install_runtime_memory_routes(
    app: flask.Flask,
    *,
    url_prefix: str,
    tracker_getter: Callable[[], PodMemoryTracker],
    logger: logging.Logger | None = None,
) -> None:
    app_logger = logger or logging.getLogger(__name__)

    def _get_snapshot() -> MemorySeriesSnapshot:
        return tracker_getter().get_snapshot()

    @app.route(f"{url_prefix}/api/runtime/memory-series")
    def runtime_memory_series() -> flask.Response:
        snapshot = _get_snapshot()
        return flask.jsonify(
            {
                "started_at": snapshot.started_at.isoformat() if snapshot.started_at is not None else None,
                "sample_interval_sec": snapshot.sample_interval_sec,
                "samples": [
                    {
                        "timestamp": sample.timestamp.isoformat(),
                        "pod_memory_bytes": sample.pod_memory_bytes,
                        "selenium_memory_bytes": sample.selenium_memory_bytes,
                    }
                    for sample in snapshot.samples
                ],
            }
        )

    @app.route(f"{url_prefix}/api/runtime/memory-graph.svg")
    def runtime_memory_graph() -> flask.Response:
        snapshot = _get_snapshot()
        svg = generate_memory_usage_svg(snapshot)
        response = flask.Response(svg, mimetype="image/svg+xml")
        response.headers["Cache-Control"] = "no-store"
        return response

    app_logger.debug("Installed runtime memory routes at %s", url_prefix)
