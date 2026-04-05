from __future__ import annotations

from dataclasses import dataclass

import price_platform.managers.crawl_runtime
from price_platform.managers import (
    managed_crawl_runtime,
)


@dataclass
class DummyNotificationManager:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


def test_managed_crawl_runtime_initializes_and_cleans_up() -> None:
    cleared: list[DummyNotificationManager | None] = []
    manager = DummyNotificationManager()

    with managed_crawl_runtime(
        liveness_file=None,
        liveness_update_interval_sec=15,
        enable_notification=True,
        init_notification_manager=lambda: manager,
        clear_notification_manager=cleared.append,
    ) as runtime:
        assert runtime.notification_manager is manager

    assert manager.stopped is True
    assert cleared == [None]


def test_managed_crawl_runtime_skips_notification_when_disabled() -> None:
    init_calls: list[str] = []
    cleared: list[DummyNotificationManager | None] = []

    with managed_crawl_runtime(
        liveness_file=None,
        liveness_update_interval_sec=15,
        enable_notification=False,
        init_notification_manager=lambda: init_calls.append("init") or DummyNotificationManager(),
        clear_notification_manager=cleared.append,
    ) as runtime:
        assert runtime.notification_manager is None

    assert init_calls == []
    assert cleared == [None]


def _check_protocol_conformance() -> None:
    """型チェッカーが Protocol 適合性を検証する."""
    _: price_platform.managers.crawl_runtime.SupportsStop = DummyNotificationManager()
