"""Typed notification payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _SupportsValue(Protocol):
    @property
    def value(self) -> str: ...


class SupportsNotificationEvent(Protocol):
    id: int
    event_type: _SupportsValue
    product_id: str
    store: _SupportsValue | str
    price: int
    url: str | None


@dataclass(frozen=True)
class NotificationPayload:
    """Canonical payload persisted in the notification queue."""

    event_id: int
    event_type: str
    product_id: str
    store: str
    price: int
    url: str | None
    message: str


def build_notification_payload(
    payload_or_event: NotificationPayload | SupportsNotificationEvent,
    message: str | None = None,
) -> NotificationPayload:
    """Normalize queue inputs into the canonical payload DTO."""
    if isinstance(payload_or_event, NotificationPayload):
        if message is None:
            return payload_or_event
        return NotificationPayload(
            event_id=payload_or_event.event_id,
            event_type=payload_or_event.event_type,
            product_id=payload_or_event.product_id,
            store=payload_or_event.store,
            price=payload_or_event.price,
            url=payload_or_event.url,
            message=message,
        )

    if message is None:
        msg = "message is required when enqueueing from an event object"
        raise ValueError(msg)

    store_ref = payload_or_event.store
    store = store_ref if isinstance(store_ref, str) else store_ref.value
    return NotificationPayload(
        event_id=payload_or_event.id,
        event_type=payload_or_event.event_type.value,
        product_id=payload_or_event.product_id,
        store=store,
        price=payload_or_event.price,
        url=payload_or_event.url,
        message=message,
    )
