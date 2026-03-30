"""Shared helpers for notification status endpoints."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol


class TwitterStoreProtocol(Protocol):
    """Store surface required for Twitter status reporting."""

    def get_pending_count(self) -> int: ...

    def get_last_posted_time(self) -> datetime | None: ...

    def get_rate_limit_state(self) -> Any | None: ...


class WebPushStatusStoreProtocol(Protocol):
    """Store surface required for Web Push status reporting."""

    def get_subscription_count(self) -> int: ...

    def get_delivery_stats(self, days: int = 30) -> dict[str, int]: ...

    def get_group_subscription_stats(self) -> dict[str, int]: ...

    def get_product_subscription_stats(self) -> dict[str, int]: ...

    def get_last_delivery_time(self) -> datetime | None: ...


def build_twitter_status_payload(
    *,
    store: TwitterStoreProtocol,
    now: datetime,
    elapsed_seconds_factory: Callable[[float], Any] | None = None,
    wait_seconds_factory: Callable[[float], Any] | None = None,
    wait_minutes_factory: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Build Twitter status payload from a notification store."""
    elapsed_seconds_factory = elapsed_seconds_factory or (lambda seconds: seconds)
    wait_seconds_factory = wait_seconds_factory or (lambda seconds: seconds)
    wait_minutes_factory = wait_minutes_factory or (lambda minutes: minutes)

    payload: dict[str, Any] = {
        "enabled": True,
        "pending_count": store.get_pending_count(),
    }

    last_posted_time = store.get_last_posted_time()
    if last_posted_time is not None:
        payload["last_posted_at"] = last_posted_time.isoformat()
        payload["last_posted_ago_sec"] = elapsed_seconds_factory((now - last_posted_time).total_seconds())

    rate_limit_state = store.get_rate_limit_state()
    if rate_limit_state is None:
        payload["rate_limited"] = False
        return payload

    next_available = rate_limit_state.next_available_at
    if next_available > now:
        wait_seconds = (next_available - now).total_seconds()
        payload["rate_limited"] = True
        payload["rate_limit"] = {
            "next_available_at": next_available.isoformat(),
            "wait_seconds": wait_seconds_factory(wait_seconds),
            "wait_minutes": wait_minutes_factory(wait_seconds / 60),
            "app_reset_at": rate_limit_state.app_reset.isoformat(),
            "user_reset_at": rate_limit_state.user_reset.isoformat(),
            "recorded_at": rate_limit_state.recorded_at.isoformat(),
        }
    else:
        payload["rate_limited"] = False

    return payload


def build_webpush_status_payload(
    *,
    store: WebPushStatusStoreProtocol,
    now: datetime,
    days: int,
    product_group_resolver: Callable[[str], str | None],
    group_stats_key: str,
    grouped_products_key: str,
    elapsed_seconds_factory: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Build Web Push status payload from a Web Push store."""
    elapsed_seconds_factory = elapsed_seconds_factory or (lambda seconds: seconds)
    delivery_stats = store.get_delivery_stats(days=days)
    total = delivery_stats.get("total", 0)
    sent = delivery_stats.get("sent", 0)
    failed = delivery_stats.get("failed", 0)
    expired = delivery_stats.get("expired", 0)

    grouped_products: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"product_count": 0, "subscriber_count": 0}
    )
    for product_id, subscriber_count in store.get_product_subscription_stats().items():
        group = product_group_resolver(product_id)
        if group is None:
            continue
        grouped_products[group]["product_count"] += 1
        grouped_products[group]["subscriber_count"] += subscriber_count

    payload: dict[str, Any] = {
        "enabled": True,
        "subscription_count": store.get_subscription_count(),
        "delivery": {
            "total": total,
            "sent": sent,
            "failed": failed,
            "expired": expired,
            "success_rate": round((sent / total * 100), 1) if total > 0 else 100.0,
        },
        group_stats_key: store.get_group_subscription_stats(),
        grouped_products_key: dict(grouped_products),
        "days": days,
    }

    last_delivery = store.get_last_delivery_time()
    if last_delivery is not None:
        payload["last_delivery_at"] = last_delivery.isoformat()
        payload["last_delivery_ago_sec"] = elapsed_seconds_factory((now - last_delivery).total_seconds())

    return payload
