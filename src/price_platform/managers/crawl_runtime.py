"""Shared crawl runtime orchestration helpers."""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from .lifecycle_manager import LifecycleManager, init_lifecycle_manager, set_lifecycle_manager
from .liveness_manager import LivenessManager, init_liveness_manager, set_liveness_manager


class SupportsStop(Protocol):
    """Protocol for managers that need explicit shutdown."""

    def stop(self) -> None:
        """Stop the manager and release resources."""


NotificationManagerT = TypeVar("NotificationManagerT", bound=SupportsStop)


@dataclass(frozen=True)
class CrawlRuntime(Generic[NotificationManagerT]):
    """Runtime services for a crawl session."""

    lifecycle_manager: LifecycleManager
    liveness_manager: LivenessManager
    notification_manager: NotificationManagerT | None


@contextmanager
def managed_crawl_runtime(
    *,
    liveness_file: pathlib.Path | None,
    liveness_update_interval_sec: int,
    enable_notification: bool,
    init_notification_manager: Callable[[], NotificationManagerT],
    clear_notification_manager: Callable[[NotificationManagerT | None], None],
) -> Iterator[CrawlRuntime[NotificationManagerT]]:
    """Create and clean up per-run managers for a crawl session."""
    lifecycle_manager = init_lifecycle_manager()
    liveness_manager = init_liveness_manager(
        liveness_file,
        update_interval_sec=liveness_update_interval_sec,
    )
    notification_manager = init_notification_manager() if enable_notification else None

    try:
        yield CrawlRuntime(
            lifecycle_manager=lifecycle_manager,
            liveness_manager=liveness_manager,
            notification_manager=notification_manager,
        )
    finally:
        if notification_manager is not None:
            notification_manager.stop()
        clear_notification_manager(None)
        set_liveness_manager(None)
        set_lifecycle_manager(None)
