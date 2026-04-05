from __future__ import annotations

import logging
import signal
import unittest.mock

import price_platform.cli


def test_lifecycle_controller_requests_shutdown(monkeypatch) -> None:
    handlers: dict[int, object] = {}

    monkeypatch.setattr(
        signal,
        "signal",
        unittest.mock.create_autospec(
            signal.signal,
            side_effect=lambda signum, handler: handlers.setdefault(signum, handler),
        ),
    )

    controller = price_platform.cli.LifecycleController()
    controller.install_signal_handlers(logger=logging.getLogger(__name__), exit_fn=lambda code: None)

    handler = handlers[signal.SIGTERM]
    handler(signal.SIGTERM, None)

    assert controller.manager.is_shutdown_requested() is True
    assert controller.manager.get_exit_reason() == "sigterm"


def test_initialize_cli_returns_reset_controller(monkeypatch) -> None:
    init_calls: list[str] = []

    monkeypatch.setattr(
        price_platform.cli,
        "setup_logging",
        unittest.mock.create_autospec(
            price_platform.cli.setup_logging,
            side_effect=lambda verbose=False: init_calls.append(f"log:{verbose}"),
        ),
    )
    monkeypatch.setattr(
        price_platform.cli.LifecycleController,
        "install_signal_handlers",
        unittest.mock.create_autospec(
            price_platform.cli.LifecycleController.install_signal_handlers,
            side_effect=lambda self, **kwargs: init_calls.append("signals"),
        ),
    )

    controller = price_platform.cli.initialize_cli(
        verbose=False,
        debug_mode=True,
        logger=logging.getLogger(__name__),
    )

    assert controller.manager.is_shutdown_requested() is False
    assert init_calls == ["log:True", "signals"]
