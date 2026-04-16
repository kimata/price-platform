"""In-memory pod and Selenium memory sampling."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from price_platform.platform import clock


@dataclass(frozen=True)
class MemorySample:
    timestamp: datetime
    pod_memory_bytes: int | None
    selenium_memory_bytes: int | None


@dataclass(frozen=True)
class MemorySeriesSnapshot:
    started_at: datetime | None
    sample_interval_sec: int
    samples: tuple[MemorySample, ...]


class PodMemoryTracker:
    """Collect pod and Selenium memory samples into an in-memory ring buffer."""

    def __init__(
        self,
        *,
        sample_interval_sec: int = 60,
        max_samples: int = 10080,
        now_fn: Callable[[], datetime] | None = None,
        sample_fn: Callable[[], tuple[int | None, int | None]] | None = None,
    ) -> None:
        self._sample_interval_sec = sample_interval_sec
        self._samples: deque[MemorySample] = deque(maxlen=max_samples)
        self._now_fn = now_fn or clock.now
        self._sample_fn = sample_fn or self._default_sample_fn
        self._started_at: datetime | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def sample_interval_sec(self) -> int:
        return self._sample_interval_sec

    def start(self, started_at: datetime | None = None) -> None:
        self.stop()
        with self._lock:
            self._started_at = started_at or self._now_fn()
            self._samples.clear()
        self._stop_event = threading.Event()
        self.sample_now(timestamp=self._started_at)
        self._thread = threading.Thread(target=self._run, name="pod-memory-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout=max(self._sample_interval_sec, 1))
        self._thread = None

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def sample_now(self, *, timestamp: datetime | None = None) -> MemorySample:
        pod_memory_bytes, selenium_memory_bytes = self._sample_fn()
        sample = MemorySample(
            timestamp=timestamp or self._now_fn(),
            pod_memory_bytes=pod_memory_bytes,
            selenium_memory_bytes=selenium_memory_bytes,
        )
        with self._lock:
            self._samples.append(sample)
        return sample

    def get_snapshot(self) -> MemorySeriesSnapshot:
        with self._lock:
            return MemorySeriesSnapshot(
                started_at=self._started_at,
                sample_interval_sec=self._sample_interval_sec,
                samples=tuple(self._samples),
            )

    def _run(self) -> None:
        while not self._stop_event.wait(self._sample_interval_sec):
            self.sample_now()

    @staticmethod
    def _default_sample_fn() -> tuple[int | None, int | None]:
        import my_lib.memory_util

        return (
            my_lib.memory_util.read_pod_memory_bytes(),
            my_lib.memory_util.read_selenium_memory_bytes(),
        )
