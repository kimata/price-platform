"""Lifecycle manager for price-platform applications.

Provides thread-safe shutdown management using threading.Event.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LifecycleManager:
    """Thread-safe lifecycle manager for shutdown coordination.

    This class provides a centralized way to request and check for
    application shutdown, using threading.Event for thread-safety.
    """

    _shutdown_event: threading.Event = field(default_factory=threading.Event)
    _exit_reason: str | None = field(default=None)

    def request_shutdown(self, exit_reason: str = "shutdown") -> None:
        """Request application shutdown.

        This sets the internal shutdown event, which can be checked by
        other threads to coordinate graceful shutdown.

        Args:
            exit_reason: The reason for shutdown (e.g., "shutdown", "sigterm").
        """
        self._exit_reason = exit_reason
        self._shutdown_event.set()
        logger.info(f"シャットダウンが要求されました (reason: {exit_reason})")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested.

        Returns:
            True if shutdown has been requested, False otherwise.
        """
        return self._shutdown_event.is_set()

    def get_exit_reason(self) -> str | None:
        """Get the exit reason if shutdown was requested.

        Returns:
            The exit reason string, or None if shutdown was not requested.
        """
        return self._exit_reason

    def reset(self) -> None:
        """Reset shutdown state.

        This clears the shutdown event, allowing the application to
        continue running. Useful for testing or restart scenarios.
        """
        self._shutdown_event.clear()
        self._exit_reason = None
        logger.debug("シャットダウン状態をリセット")

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for shutdown to be requested.

        Args:
            timeout: Maximum time to wait in seconds (None for indefinite).

        Returns:
            True if shutdown was requested within timeout, False if timeout
            expired without shutdown being requested.
        """
        return self._shutdown_event.wait(timeout)


# Global lifecycle manager instance
_lifecycle_manager: LifecycleManager | None = None


def get_lifecycle_manager() -> LifecycleManager | None:
    """Get the global lifecycle manager instance.

    Returns:
        The lifecycle manager instance, or None if not initialized.
    """
    return _lifecycle_manager


def set_lifecycle_manager(manager: LifecycleManager | None) -> None:
    """Set the global lifecycle manager instance.

    Args:
        manager: The lifecycle manager to set, or None to clear.
    """
    global _lifecycle_manager
    _lifecycle_manager = manager


def init_lifecycle_manager() -> LifecycleManager:
    """Initialize and return a new lifecycle manager.

    This creates a new LifecycleManager instance and sets it as the
    global instance.

    Returns:
        The newly created lifecycle manager.
    """
    manager = LifecycleManager()
    set_lifecycle_manager(manager)
    return manager


def _reset_lifecycle_manager() -> None:
    """Reset lifecycle manager for testing."""
    global _lifecycle_manager
    _lifecycle_manager = None
