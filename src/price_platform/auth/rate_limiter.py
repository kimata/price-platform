"""Rate limiting helpers for price-platform authentication."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateLimitSettings:
    """Rate limiting configuration."""

    failure_window_sec: int = 10 * 60
    max_failures: int = 5
    lockout_duration_sec: int = 3 * 60 * 60


@dataclass
class _RateLimitState:
    failures: dict[str, list[float]] = field(default_factory=dict)
    lockouts: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class InMemoryRateLimiter:
    """Simple in-memory rate limiter for authentication endpoints."""

    def __init__(
        self,
        settings: RateLimitSettings | None = None,
        *,
        now_fn: Callable[[], float] | None = None,
    ):
        self.settings = settings or RateLimitSettings()
        self._now_fn = now_fn or time.time
        self._state = _RateLimitState()

    def is_locked_out(self, ip: str) -> bool:
        with self._state.lock:
            lockout_until = self._state.lockouts.get(ip)
            if lockout_until is None:
                return False

            now = self._now_fn()
            if now < lockout_until:
                return True

            del self._state.lockouts[ip]
            return False

    def record_failure(self, ip: str) -> bool:
        now = self._now_fn()
        with self._state.lock:
            if ip in self._state.lockouts and now < self._state.lockouts[ip]:
                return False

            failures = self._state.failures.setdefault(ip, [])
            cutoff = now - self.settings.failure_window_sec
            recent_failures = [timestamp for timestamp in failures if timestamp > cutoff]
            recent_failures.append(now)
            self._state.failures[ip] = recent_failures

            if len(recent_failures) >= self.settings.max_failures:
                self._state.lockouts[ip] = now + self.settings.lockout_duration_sec
                del self._state.failures[ip]
                return True

            return False

    def get_lockout_remaining_sec(self, ip: str) -> int:
        with self._state.lock:
            lockout_until = self._state.lockouts.get(ip)
            if lockout_until is None:
                return 0

            return max(0, int(lockout_until - self._now_fn()))

    def clear_failures(self, ip: str) -> None:
        with self._state.lock:
            self._state.failures.pop(ip, None)
            self._state.lockouts.pop(ip, None)

    def clear_state(self) -> None:
        with self._state.lock:
            self._state.failures.clear()
            self._state.lockouts.clear()
