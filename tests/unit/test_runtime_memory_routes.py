from __future__ import annotations

from datetime import datetime

import flask

import price_platform.managers
import price_platform.webapp


class _TrackerStub:
    def get_snapshot(self) -> price_platform.managers.MemorySeriesSnapshot:
        return price_platform.managers.MemorySeriesSnapshot(
            started_at=datetime(2026, 4, 4, 10, 0, 0),
            sample_interval_sec=60,
            samples=(
                price_platform.managers.MemorySample(
                    timestamp=datetime(2026, 4, 4, 10, 0, 0),
                    pod_memory_bytes=300 * 1024 * 1024,
                    selenium_memory_bytes=180 * 1024 * 1024,
                ),
                price_platform.managers.MemorySample(
                    timestamp=datetime(2026, 4, 4, 10, 1, 0),
                    pod_memory_bytes=320 * 1024 * 1024,
                    selenium_memory_bytes=190 * 1024 * 1024,
                ),
            ),
        )


def test_install_runtime_memory_routes_serves_json_and_svg() -> None:
    app = flask.Flask(__name__)
    price_platform.webapp.install_runtime_memory_routes(
        app,
        url_prefix="/metrics",
        tracker_getter=lambda: _TrackerStub(),
    )

    client = app.test_client()

    series = client.get("/metrics/api/runtime/memory-series")
    assert series.status_code == 200
    body = series.get_json()
    assert body["sample_interval_sec"] == 60
    assert body["samples"][0]["pod_memory_bytes"] == 300 * 1024 * 1024
    assert body["samples"][0]["selenium_memory_bytes"] == 180 * 1024 * 1024

    graph = client.get("/metrics/api/runtime/memory-graph.svg")
    assert graph.status_code == 200
    assert graph.headers["Content-Type"].startswith("image/svg+xml")
    assert "Pod total" in graph.get_data(as_text=True)
    assert "Selenium" in graph.get_data(as_text=True)
