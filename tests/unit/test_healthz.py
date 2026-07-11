from __future__ import annotations

from datetime import UTC, datetime
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
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
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
        lambda: datetime(2024, 1, 1, 1, tzinfo=UTC),
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


def test_check_detection_activity() -> None:
    """F1: ゼロ検出の検知."""
    from dataclasses import replace as dc_replace
    from unittest.mock import MagicMock

    import price_platform.healthz as healthz

    definition = healthz.HealthzCliDefinition(
        program_name="test",
        logger_name="test",
        api_healthz_url="http://localhost/healthz",
        product_label="products",
        config_loader=None,
        metrics_db_factory=None,
        total_product_count_getter=None,
        detection_expected_event_types=("PRICE_DROP",),
    )

    # factory 未設定 → スキップして True
    assert healthz.check_detection_activity(MagicMock(), definition)

    # 検出あり → True
    event_store = MagicMock()
    event_store.get_event_counts_by_type.return_value = {"ALL_TIME_LOW": 3}
    with_factory = dc_replace(definition, price_event_store_factory=lambda _config: event_store)
    assert healthz.check_detection_activity(MagicMock(), with_factory)

    # 全種別ゼロ → False
    event_store.get_event_counts_by_type.return_value = {}
    assert not healthz.check_detection_activity(MagicMock(), with_factory)
