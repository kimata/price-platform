"""Metrics manager for crawl session tracking.

Provides a high-level interface for collecting crawl metrics,
managing session lifecycle and accumulating store-level statistics.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


def _default_now_fn() -> datetime:
    """Default now function using my_lib.time."""
    import my_lib.time

    return my_lib.time.now()


@runtime_checkable
class MetricsDBProtocol(Protocol):
    """Protocol for metrics database operations.

    Each consuming application provides a concrete implementation
    (typically ``MetricsDB`` in its ``metrics.py`` module).
    """

    def start_session(self) -> int: ...

    def end_session(self, session_id: int, exit_reason: str) -> None: ...

    def close_interrupted_sessions(self) -> int: ...

    def update_session_counts(
        self,
        session_id: int,
        *,
        total_items: int,
        success_items: int,
        failed_items: int,
        total_products: int,
        success_products: int,
    ) -> None: ...

    def mark_work_ended(self, session_id: int) -> None: ...

    def update_heartbeat(self, session_id: int) -> None: ...

    def record_item_stats(
        self,
        *,
        session_id: int,
        store_name: str,
        product_id: str,
        started_at: datetime,
        duration_sec: float,
        success: bool,
        error_message: str | None = ...,
    ) -> None: ...

    def record_amazon_batch(
        self,
        *,
        session_id: int,
        started_at: datetime,
        duration_sec: float,
        product_count: int,
        success: bool,
        error_message: str | None = ...,
    ) -> None: ...

    def record_store_stats(
        self,
        *,
        session_id: int,
        store_name: str,
        total_items: int,
        success_count: int,
        failed_count: int,
        total_duration_sec: float,
    ) -> None: ...

    def increment_round_count(self, session_id: int) -> int: ...


@dataclass
class StoreMetricsAccumulator:
    """Accumulator for store-level metrics during a session."""

    store_name: str
    total_items: int = 0
    success_count: int = 0
    failed_count: int = 0
    total_duration_sec: float = 0.0


@dataclass
class ItemTimingContext:
    """Context for timing a single item crawl."""

    session_id: int
    store_name: str
    product_id: str
    started_at: datetime
    _manager: MetricsManager
    _start_time: float = field(default_factory=time.perf_counter)

    def success(self) -> None:
        """Mark item as successfully crawled."""
        duration_sec = time.perf_counter() - self._start_time
        self._manager._record_item_complete(
            session_id=self.session_id,
            store_name=self.store_name,
            product_id=self.product_id,
            started_at=self.started_at,
            duration_sec=duration_sec,
            success=True,
        )

    def failure(self, error_message: str | None = None) -> None:
        """Mark item as failed."""
        duration_sec = time.perf_counter() - self._start_time
        self._manager._record_item_complete(
            session_id=self.session_id,
            store_name=self.store_name,
            product_id=self.product_id,
            started_at=self.started_at,
            duration_sec=duration_sec,
            success=False,
            error_message=error_message,
        )


class MetricsManager:
    """Manager for crawl session metrics collection.

    This class provides a high-level interface for collecting crawl metrics.
    It manages session lifecycle and accumulates store-level statistics.

    Args:
        db: A metrics database instance satisfying ``MetricsDBProtocol``.
        now_fn: Callable returning the current datetime. Defaults to
            ``my_lib.time.now()``. Override for testing.
    """

    def __init__(
        self,
        db: MetricsDBProtocol,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ):
        """Initialize metrics manager."""
        self._db = db
        self._now_fn = now_fn or _default_now_fn
        self._current_session_id: int | None = None
        self._store_accumulators: dict[str, StoreMetricsAccumulator] = {}
        self._total_items = 0
        self._success_items = 0
        self._failed_items = 0
        self._processed_product_ids: set[str] = set()
        self._success_product_ids: set[str] = set()

    @property
    def session_id(self) -> int | None:
        """Get current session ID."""
        return self._current_session_id

    @property
    def has_active_session(self) -> bool:
        """Check if there is an active session."""
        return self._current_session_id is not None

    def start_session(self) -> int:
        """Start a new metrics session."""
        closed_count = self._db.close_interrupted_sessions()
        if closed_count > 0:
            logger.info(f"Closed {closed_count} interrupted session(s) from previous run")

        if self._current_session_id is not None:
            logger.warning(f"Session {self._current_session_id} already active, ending it first")
            self.end_session("replaced")

        self._current_session_id = self._db.start_session()
        self._store_accumulators = {}
        self._total_items = 0
        self._success_items = 0
        self._failed_items = 0
        self._processed_product_ids = set()
        self._success_product_ids = set()
        logger.info(f"Started metrics session {self._current_session_id}")
        return self._current_session_id

    def end_session(self, exit_reason: str = "normal") -> None:
        """End the current metrics session."""
        if self._current_session_id is None:
            logger.warning("No active session to end")
            return

        self._flush_store_stats()

        self._db.update_session_counts(
            self._current_session_id,
            total_items=self._total_items,
            success_items=self._success_items,
            failed_items=self._failed_items,
            total_products=len(self._processed_product_ids),
            success_products=len(self._success_product_ids),
        )

        self._db.end_session(self._current_session_id, exit_reason)
        logger.info(f"Ended metrics session {self._current_session_id}: {exit_reason}")
        self._current_session_id = None

    def mark_work_ended(self) -> None:
        """Mark when actual crawl work has ended (before sleep interval)."""
        if self._current_session_id is None:
            return
        self._db.mark_work_ended(self._current_session_id)

    def update_heartbeat(self) -> None:
        """Update session heartbeat."""
        if self._current_session_id is None:
            return
        self._db.update_heartbeat(self._current_session_id)

    def start_item(self, store_name: str, product_id: str) -> ItemTimingContext:
        """Start timing a single item crawl.

        Returns a context object that should be used to record success or failure.
        """
        if self._current_session_id is None:
            raise RuntimeError("No active metrics session")

        return ItemTimingContext(
            session_id=self._current_session_id,
            store_name=store_name,
            product_id=product_id,
            started_at=self._now_fn(),
            _manager=self,
        )

    def _record_item_complete(
        self,
        session_id: int,
        store_name: str,
        product_id: str,
        started_at: datetime,
        duration_sec: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Record completion of a single item crawl (internal)."""
        self._db.record_item_stats(
            session_id=session_id,
            store_name=store_name,
            product_id=product_id,
            started_at=started_at,
            duration_sec=duration_sec,
            success=success,
            error_message=error_message,
        )

        if store_name not in self._store_accumulators:
            self._store_accumulators[store_name] = StoreMetricsAccumulator(store_name=store_name)

        acc = self._store_accumulators[store_name]
        acc.total_items += 1
        if success:
            acc.success_count += 1
            acc.total_duration_sec += duration_sec
        else:
            acc.failed_count += 1

        self._total_items += 1
        self._processed_product_ids.add(product_id)
        if success:
            self._success_items += 1
            self._success_product_ids.add(product_id)
        else:
            self._failed_items += 1

    def record_amazon_batch(
        self,
        started_at: datetime,
        duration_sec: float,
        product_ids: list[str],
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Record Amazon API batch processing statistics."""
        if self._current_session_id is None:
            logger.warning("No active session for Amazon batch recording")
            return

        product_count = len(product_ids)

        self._db.record_amazon_batch(
            session_id=self._current_session_id,
            started_at=started_at,
            duration_sec=duration_sec,
            product_count=product_count,
            success=success,
            error_message=error_message,
        )

        store_name = "amazon"
        if store_name not in self._store_accumulators:
            self._store_accumulators[store_name] = StoreMetricsAccumulator(store_name=store_name)

        acc = self._store_accumulators[store_name]
        acc.total_items += product_count
        if success:
            acc.success_count += product_count
            acc.total_duration_sec += duration_sec
        else:
            acc.failed_count += product_count

        self._total_items += product_count
        if success:
            self._success_items += product_count
        else:
            self._failed_items += product_count

    def flush_and_heartbeat(self) -> None:
        """Flush accumulated stats and update heartbeat.

        Call this periodically (e.g., after each batch save).
        """
        if self._current_session_id is None:
            return

        self._flush_store_stats()
        self._db.update_session_counts(
            self._current_session_id,
            total_items=self._total_items,
            success_items=self._success_items,
            failed_items=self._failed_items,
            total_products=len(self._processed_product_ids),
            success_products=len(self._success_product_ids),
        )
        self._db.update_heartbeat(self._current_session_id)

    def complete_round(self) -> int:
        """Mark a crawl round as complete and return the new round count.

        Call this after each complete iteration through all products.
        Returns the total number of completed rounds.
        """
        if self._current_session_id is None:
            logger.warning("No active session for round completion")
            return 0

        round_count = self._db.increment_round_count(self._current_session_id)
        logger.info(f"巡回完了: ラウンド {round_count}")
        return round_count

    def _flush_store_stats(self) -> None:
        """Flush accumulated store stats to database."""
        if self._current_session_id is None:
            return

        for acc in self._store_accumulators.values():
            self._db.record_store_stats(
                session_id=self._current_session_id,
                store_name=acc.store_name,
                total_items=acc.total_items,
                success_count=acc.success_count,
                failed_count=acc.failed_count,
                total_duration_sec=acc.total_duration_sec,
            )

    def get_session_summary(self) -> dict[str, Any]:
        """Get current session summary for logging."""
        return {
            "session_id": self._current_session_id,
            "total_items": self._total_items,
            "success_items": self._success_items,
            "failed_items": self._failed_items,
            "total_products": len(self._processed_product_ids),
            "success_products": len(self._success_product_ids),
            "stores": {
                name: {
                    "total": acc.total_items,
                    "success": acc.success_count,
                    "failed": acc.failed_count,
                    "avg_duration": acc.total_duration_sec / acc.success_count if acc.success_count else 0,
                }
                for name, acc in self._store_accumulators.items()
            },
        }


_manager: MetricsManager | None = None


def get_metrics_manager() -> MetricsManager | None:
    """Get global metrics manager instance (may be None if not enabled)."""
    return _manager


def set_metrics_manager(manager: MetricsManager | None) -> None:
    """Set global metrics manager instance."""
    global _manager
    _manager = manager
