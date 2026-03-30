"""Shared CLI bootstrap helpers for price-platform consumer apps."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Callable


def setup_logging(verbose: bool = False) -> None:
    """Configure a standard console logger for crawler CLIs."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def install_shutdown_signal_handlers(
    *,
    request_shutdown: Callable[[str], None],
    logger: logging.Logger,
    exit_fn: Callable[[int], None] = sys.exit,
) -> None:
    """Install SIGINT/SIGTERM handlers with double-tap force exit behavior."""
    force_exit = {"value": False}

    def signal_handler(signum: int, _frame: object) -> None:
        if force_exit["value"]:
            logger.warning("強制終了します")
            exit_fn(1)

        force_exit["value"] = True
        exit_reason = "sigterm" if signum == signal.SIGTERM else "sigint"
        logger.info(f"シャットダウン中 ({exit_reason})... (もう一度 Ctrl-C で強制終了)")
        request_shutdown(exit_reason)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def initialize_cli(
    *,
    verbose: bool,
    debug_mode: bool,
    reset_shutdown: Callable[[], None],
    request_shutdown: Callable[[str], None],
    logger: logging.Logger,
) -> None:
    """Initialize shared CLI concerns before running an app-specific crawl."""
    setup_logging(verbose or debug_mode)
    reset_shutdown()
    install_shutdown_signal_handlers(
        request_shutdown=request_shutdown,
        logger=logger,
    )
