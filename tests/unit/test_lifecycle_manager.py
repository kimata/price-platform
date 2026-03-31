from __future__ import annotations

from price_platform.managers.lifecycle_manager import LifecycleManager


def test_request_shutdown_sets_exit_reason() -> None:
    manager = LifecycleManager()

    manager.request_shutdown("sigterm")

    assert manager.is_shutdown_requested() is True
    assert manager.get_exit_reason() == "sigterm"


def test_reset_clears_shutdown_state() -> None:
    manager = LifecycleManager()
    manager.request_shutdown("sigint")

    manager.reset()

    assert manager.is_shutdown_requested() is False
    assert manager.get_exit_reason() is None
