"""Liveness manager for price-platform applications.

Provides liveness file management and interruptible sleep functionality.
"""

from __future__ import annotations

import logging
import pathlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from price_platform.platform import footprint

logger = logging.getLogger(__name__)

# Default liveness update interval in seconds
DEFAULT_UPDATE_INTERVAL = 30
_liveness_manager: LivenessManager | None = None


def _default_update_fn(path: pathlib.Path) -> None:
    """Default liveness update using the local footprint adapter."""
    footprint.update(path)


@dataclass
class LivenessManager:
    """Manager for liveness file updates and interruptible sleep.

    This class provides centralized management of liveness file updates
    and interruptible sleep functionality that can be interrupted by
    shutdown signals.

    Args:
        liveness_file: Path to liveness file (None to disable updates).
        update_interval_sec: Interval for liveness updates.
        update_fn: Callable to update the liveness file. Defaults to
            ``my_lib.footprint.update``. Override for testing.
    """

    liveness_file: pathlib.Path | None
    update_interval_sec: int = DEFAULT_UPDATE_INTERVAL
    update_fn: Callable[[pathlib.Path], None] = field(default=_default_update_fn)

    def update(self) -> None:
        """Update the liveness file.

        If no liveness file is configured, this is a no-op.
        """
        if self.liveness_file is None:
            return

        self.update_fn(self.liveness_file)
        logger.debug(f"Liveness updated: {self.liveness_file}")

    def interruptible_sleep(
        self,
        duration_sec: float,
        shutdown_check: Callable[[], bool],
    ) -> bool:
        """Execute an interruptible sleep.

        Sleep for the specified duration in intervals, checking for shutdown
        and updating liveness file at each interval.

        Args:
            duration_sec: Total duration to sleep in seconds.
            shutdown_check: Callback to check if shutdown has been requested.

        Returns:
            True if sleep completed normally, False if interrupted by shutdown.
        """
        elapsed = 0.0
        check_interval = float(self.update_interval_sec)

        while elapsed < duration_sec:
            if shutdown_check():
                logger.info("シャットダウンが要求されたため、スリープを中断します")
                return False

            # Update liveness
            self.update()

            # Calculate next sleep interval
            sleep_time = min(check_interval, duration_sec - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

        # Final liveness update
        self.update()

        return True


def get_liveness_manager() -> LivenessManager | None:
    """Return the process-global liveness manager."""
    return _liveness_manager


def set_liveness_manager(manager: LivenessManager | None) -> None:
    """Replace the process-global liveness manager."""
    global _liveness_manager
    _liveness_manager = manager


def init_liveness_manager(
    *,
    liveness_file: pathlib.Path | None,
    update_interval_sec: int = DEFAULT_UPDATE_INTERVAL,
    update_fn: Callable[[pathlib.Path], None] = _default_update_fn,
) -> LivenessManager:
    """Create and register the process-global liveness manager."""
    manager = LivenessManager(
        liveness_file=liveness_file,
        update_interval_sec=update_interval_sec,
        update_fn=update_fn,
    )
    set_liveness_manager(manager)
    return manager


def _reset_liveness_manager() -> None:
    """Clear the process-global liveness manager for tests."""
    set_liveness_manager(None)
