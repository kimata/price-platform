from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from price_platform.notification import NotificationPayload
from price_platform.notification.notification_store import NotificationStore


class _EventType(Enum):
    PRICE_DROP = "price_drop"


class _Store(Enum):
    AMAZON = "amazon"


@dataclass(frozen=True)
class _Event:
    id: int
    event_type: _EventType
    product_id: str
    store: _Store
    price: int
    url: str | None


def test_enqueue_accepts_notification_payload(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "notification.db")
    queue_id = store.enqueue(
        NotificationPayload(
            event_id=1,
            event_type="price_drop",
            product_id="product-1",
            store="amazon",
            price=1234,
            url="https://example.com",
            message="hello",
        )
    )

    pending = store.get_pending()

    assert queue_id > 0
    assert len(pending) == 1
    assert pending[0].message == "hello"


def test_enqueue_accepts_event_object_for_backward_compatibility(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "notification.db")
    queue_id = store.enqueue(
        _Event(
            id=7,
            event_type=_EventType.PRICE_DROP,
            product_id="product-7",
            store=_Store.AMAZON,
            price=5678,
            url=None,
        ),
        "world",
    )

    pending = store.get_pending()

    assert queue_id > 0
    assert pending[0].event_id == 7
    assert pending[0].event_type == "price_drop"
    assert pending[0].store == "amazon"
