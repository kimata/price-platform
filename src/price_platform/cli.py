"""Shared CLI bootstrap helpers for price-platform consumer apps."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from .managers.lifecycle_manager import LifecycleManager


def setup_logging(verbose: bool = False) -> None:
    """Configure a standard console logger for crawler CLIs."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@dataclass
class LifecycleController:
    """Own shutdown state for a single CLI or WebUI process."""

    manager: LifecycleManager = field(default_factory=LifecycleManager)
    _force_exit_requested: bool = False

    def reset(self) -> None:
        """Reset graceful and force-exit state."""
        self.manager.reset()
        self._force_exit_requested = False

    def request_shutdown(self, exit_reason: str = "shutdown") -> None:
        """Request graceful shutdown for the attached lifecycle manager."""
        self.manager.request_shutdown(exit_reason)

    def install_signal_handlers(
        self,
        *,
        logger: logging.Logger,
        exit_fn: Callable[[int], None] = sys.exit,
        on_shutdown: Callable[[str], None] | None = None,
    ) -> None:
        """Install SIGINT/SIGTERM handlers with double-tap force exit behavior."""

        def signal_handler(signum: int, _frame: object) -> None:
            if self._force_exit_requested:
                logger.warning("強制終了します")
                exit_fn(1)

            self._force_exit_requested = True
            exit_reason = "sigterm" if signum == signal.SIGTERM else "sigint"
            logger.info(f"シャットダウン中 ({exit_reason})... (もう一度 Ctrl-C で強制終了)")
            self.request_shutdown(exit_reason)
            if on_shutdown is not None:
                on_shutdown(exit_reason)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


def initialize_cli(
    *,
    verbose: bool,
    debug_mode: bool,
    logger: logging.Logger,
) -> LifecycleController:
    """Initialize shared CLI concerns before running an app-specific crawl."""
    setup_logging(verbose or debug_mode)
    controller = LifecycleController()
    controller.reset()
    controller.install_signal_handlers(logger=logger)
    return controller
