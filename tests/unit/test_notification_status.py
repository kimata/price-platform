from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from price_platform.notification.status import (
    build_twitter_status_payload,
    build_webpush_status_payload,
)


@dataclass(frozen=True)
class _RateLimitState:
    next_available_at: datetime
    app_reset: datetime
    user_reset: datetime
    recorded_at: datetime


class _TwitterStore:
    def __init__(self, *, last_posted_time: datetime | None, rate_limit_state: _RateLimitState | None):
        self._last_posted_time = last_posted_time
        self._rate_limit_state = rate_limit_state

    def get_pending_count(self) -> int:
        return 3

    def get_last_posted_time(self) -> datetime | None:
        return self._last_posted_time

    def get_rate_limit_state(self) -> _RateLimitState | None:
        return self._rate_limit_state


class _WebPushStore:
    def get_subscription_count(self) -> int:
        return 4

    def get_delivery_stats(self, days: int = 30) -> dict[str, int]:
        assert days == 7
        return {"total": 10, "sent": 7, "failed": 2, "expired": 1}

    def get_group_subscription_stats(self) -> dict[str, int]:
        return {"sony": 2, "canon": 1}

    def get_product_subscription_stats(self) -> dict[str, int]:
        return {"p1": 2, "p2": 1, "missing": 5}

    def get_last_delivery_time(self) -> datetime | None:
        return datetime(2026, 3, 31, 11, 50, 0)


def test_build_twitter_status_payload_supports_custom_factories() -> None:
    now = datetime(2026, 3, 31, 12, 0, 0)
    payload = build_twitter_status_payload(
        store=_TwitterStore(
            last_posted_time=now - timedelta(seconds=65),
            rate_limit_state=_RateLimitState(
                next_available_at=now + timedelta(seconds=125),
                app_reset=now + timedelta(minutes=15),
                user_reset=now + timedelta(minutes=5),
                recorded_at=now - timedelta(minutes=1),
            ),
        ),
        now=now,
        elapsed_seconds_factory=int,
        wait_seconds_factory=int,
        wait_minutes_factory=int,
    )

    assert payload["pending_count"] == 3
    assert payload["last_posted_ago_sec"] == 65
    assert payload["rate_limited"] is True
    assert payload["rate_limit"]["wait_seconds"] == 125
    assert payload["rate_limit"]["wait_minutes"] == 2


def test_build_webpush_status_payload_groups_products() -> None:
    now = datetime(2026, 3, 31, 12, 0, 0)
    payload = build_webpush_status_payload(
        store=_WebPushStore(),
        now=now,
        days=7,
        product_group_resolver=lambda product_id: {"p1": "sony", "p2": "canon"}.get(product_id),
        group_stats_key="maker_stats",
        grouped_products_key="product_by_maker",
        elapsed_seconds_factory=int,
    )

    assert payload["subscription_count"] == 4
    assert payload["delivery"]["success_rate"] == 70.0
    assert payload["maker_stats"] == {"sony": 2, "canon": 1}
    assert payload["product_by_maker"] == {
        "sony": {"product_count": 1, "subscriber_count": 2},
        "canon": {"product_count": 1, "subscriber_count": 1},
    }
    assert payload["last_delivery_ago_sec"] == 600
