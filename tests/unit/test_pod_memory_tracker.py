from __future__ import annotations

from datetime import datetime

import price_platform.managers


def test_pod_memory_tracker_samples_immediately_and_manually() -> None:
    timestamps = iter(
        [
            datetime(2026, 4, 4, 10, 0, 0),
            datetime(2026, 4, 4, 10, 1, 0),
        ]
    )
    values = iter(
        [
            (100, 60),
            (120, 70),
        ]
    )
    tracker = price_platform.managers.PodMemoryTracker(
        sample_interval_sec=3600,
        now_fn=lambda: next(timestamps),
        sample_fn=lambda: next(values),
    )

    tracker.start()
    tracker.sample_now()
    tracker.stop()

    snapshot = tracker.get_snapshot()
    assert snapshot.started_at == datetime(2026, 4, 4, 10, 0, 0)
    assert snapshot.sample_interval_sec == 3600
    assert snapshot.samples[0].pod_memory_bytes == 100
    assert snapshot.samples[0].selenium_memory_bytes == 60
    assert snapshot.samples[1].pod_memory_bytes == 120
    assert snapshot.samples[1].selenium_memory_bytes == 70


def test_pod_memory_tracker_resets_series_on_restart() -> None:
    tracker = price_platform.managers.PodMemoryTracker(
        sample_interval_sec=3600,
        now_fn=lambda: datetime(2026, 4, 4, 11, 0, 0),
        sample_fn=lambda: (256, 128),
    )

    tracker.start(started_at=datetime(2026, 4, 4, 9, 0, 0))
    tracker.stop()
    first_snapshot = tracker.get_snapshot()

    tracker.start(started_at=datetime(2026, 4, 4, 12, 0, 0))
    tracker.stop()
    second_snapshot = tracker.get_snapshot()

    assert first_snapshot.started_at == datetime(2026, 4, 4, 9, 0, 0)
    assert len(first_snapshot.samples) == 1
    assert second_snapshot.started_at == datetime(2026, 4, 4, 12, 0, 0)
    assert len(second_snapshot.samples) == 1
