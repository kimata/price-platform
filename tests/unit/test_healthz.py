from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import price_platform.healthz


class _MetricsDbStub:
    def __init__(self, healthy: bool = True):
        self.healthy = healthy

    def is_crawler_healthy(self, *, max_age_sec: int) -> bool:
        return self.healthy and max_age_sec == 120

    def get_session_status(self, *, total_product_count: int):
        return SimpleNamespace(
            is_running=True,
            session_id=1,
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            processed_items=10,
            success_items=9,
            failed_items=1,
            processed_products=4,
            total_product_count=total_product_count,
        )


def test_check_crawler_uses_shared_definition(tmp_path: Path, monkeypatch) -> None:
    liveness_calls: list[object] = []

    monkeypatch.setattr(
        price_platform.healthz.my_lib.healthz,
        "check_liveness_all",
        lambda targets: liveness_calls.append(targets) or [],
    )
    monkeypatch.setattr(
        price_platform.healthz.platform_time,
        "now",
        lambda: datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
    )

    metrics_path = tmp_path / "metrics.db"
    metrics_path.write_text("")
    config = SimpleNamespace(
        liveness=SimpleNamespace(file=SimpleNamespace(crawler=tmp_path / "crawler.healthz"), interval_sec=60),
        metrics=SimpleNamespace(db_path="metrics.db"),
        get_absolute_path=lambda path: metrics_path,
    )
    definition = price_platform.healthz.HealthzCliDefinition(
        program_name="test-healthz",
        logger_name="bot.test",
        api_healthz_url="http://localhost/test/api/healthz",
        product_label="products",
        config_loader=lambda path: None,
        metrics_db_factory=lambda path: _MetricsDbStub(),
        total_product_count_getter=lambda: 7,
    )

    assert price_platform.healthz.check_crawler(config, definition) is True
    assert len(liveness_calls) == 1


def test_check_web_servers_reports_shared_targets(monkeypatch) -> None:
    captured: list[object] = []

    monkeypatch.setattr(
        price_platform.healthz.my_lib.healthz,
        "check_healthz_all",
        lambda http_targets: captured.extend(http_targets) or [],
    )
    definition = price_platform.healthz.HealthzCliDefinition(
        program_name="test-healthz",
        logger_name="bot.test",
        api_healthz_url="http://localhost/test/api/healthz",
        product_label="products",
        config_loader=lambda path: None,
        metrics_db_factory=lambda path: _MetricsDbStub(),
        total_product_count_getter=lambda: 0,
    )

    assert price_platform.healthz.check_web_servers(SimpleNamespace(), definition) is True
    assert [target.name for target in captured] == ["flask-api", "node-ssr"]  # type: ignore[union-attr]
