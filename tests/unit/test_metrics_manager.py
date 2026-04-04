from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import price_platform.managers.metrics_manager


@dataclass
class DummyMetricsDB:
    closed_sessions: int = 0
    ended_sessions: list[tuple[int, str]] = field(default_factory=list)
    session_counts: list[dict[str, int]] = field(default_factory=list)
    item_stats: list[dict[str, object]] = field(default_factory=list)
    store_stats: list[dict[str, object]] = field(default_factory=list)
    heartbeat_calls: list[int] = field(default_factory=list)
    round_count: int = 0

    def start_session(self) -> int:
        return 42

    def end_session(self, session_id: int, exit_reason: str) -> None:
        self.ended_sessions.append((session_id, exit_reason))

    def close_interrupted_sessions(self) -> int:
        return self.closed_sessions

    def update_session_counts(
        self,
        session_id: int,
        *,
        total_items: int,
        success_items: int,
        failed_items: int,
        total_products: int,
        success_products: int,
    ) -> None:
        self.session_counts.append(
            {
                "session_id": session_id,
                "total_items": total_items,
                "success_items": success_items,
                "failed_items": failed_items,
                "total_products": total_products,
                "success_products": success_products,
            }
        )

    def mark_work_ended(self, session_id: int) -> None:
        return None

    def update_heartbeat(self, session_id: int) -> None:
        self.heartbeat_calls.append(session_id)

    def record_item_stats(
        self,
        *,
        session_id: int,
        store_name: str,
        product_id: str,
        started_at: datetime,
        duration_sec: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        self.item_stats.append(
            {
                "session_id": session_id,
                "store_name": store_name,
                "product_id": product_id,
                "success": success,
                "error_message": error_message,
            }
        )

    def record_amazon_batch(
        self,
        *,
        session_id: int,
        started_at: datetime,
        duration_sec: float,
        product_count: int,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        return None

    def record_store_stats(
        self,
        *,
        session_id: int,
        store_name: str,
        total_items: int,
        success_count: int,
        failed_count: int,
        total_duration_sec: float,
    ) -> None:
        self.store_stats.append(
            {
                "session_id": session_id,
                "store_name": store_name,
                "total_items": total_items,
                "success_count": success_count,
                "failed_count": failed_count,
            }
        )

    def increment_round_count(self, session_id: int) -> int:
        self.round_count += 1
        return self.round_count

    def cleanup_old_records(self, days: int = 365) -> int:
        return 0


@dataclass
class DummyMemoryTracker:
    started_at: list[datetime | None] = field(default_factory=list)
    stop_calls: int = 0

    def start(self, started_at: datetime | None = None) -> None:
        self.started_at.append(started_at)

    def stop(self) -> None:
        self.stop_calls += 1


def test_metrics_manager_tracks_items_and_flushes_summary() -> None:
    db = DummyMetricsDB()
    manager = price_platform.managers.metrics_manager.MetricsManager(
        db,
        now_fn=lambda: datetime(2026, 1, 1, 0, 0, 0),
    )

    session_id = manager.start_session()
    item = manager.start_item("amazon", "product-1")
    item.success()
    failed = manager.start_item("amazon", "product-2")
    failed.failure("boom")
    manager.flush_and_heartbeat()
    manager.end_session("normal")

    assert session_id == 42
    assert len(db.item_stats) == 2
    assert db.session_counts[-1]["total_items"] == 2
    assert db.session_counts[-1]["success_items"] == 1
    assert db.session_counts[-1]["failed_items"] == 1
    assert db.session_counts[-1]["total_products"] == 2
    assert db.store_stats[-1]["store_name"] == "amazon"
    assert db.heartbeat_calls == [42]
    assert db.ended_sessions == [(42, "normal")]


def test_metrics_manager_complete_round_without_session_returns_zero() -> None:
    manager = price_platform.managers.metrics_manager.MetricsManager(DummyMetricsDB())

    assert manager.complete_round() == 0


def test_metrics_manager_starts_and_stops_memory_tracker() -> None:
    tracker = DummyMemoryTracker()
    started_at = datetime(2026, 1, 2, 3, 4, 5)
    manager = price_platform.managers.metrics_manager.MetricsManager(
        DummyMetricsDB(),
        now_fn=lambda: started_at,
        memory_tracker=tracker,
    )

    manager.start_session()
    manager.end_session("normal")

    assert tracker.started_at == [started_at]
    assert tracker.stop_calls == 1
