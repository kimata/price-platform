"""Types shared by the Web Push subscription store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

LockingMode = str


class DeliveryStatus(Enum):
    SENT = "sent"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class WebPushSubscriptionRecord:
    id: int
    endpoint: str
    p256dh_key: str
    auth_key: str
    group_filter: list[str] | None
    event_type_filter: list[str] | None
    product_filter: list[str] | None
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool


@dataclass(frozen=True)
class DeliveryLogEntry:
    id: int
    subscription_id: int
    event_id: int
    status: DeliveryStatus
    sent_at: datetime
    error_message: str | None


class SubscriptionFactory(Protocol):
    def __call__(
        self,
        *,
        id: int,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        group_filter: list[str] | None,
        event_type_filter: list[str] | None,
        product_filter: list[str] | None,
        created_at: datetime,
        last_used_at: datetime | None,
        is_active: bool,
    ) -> WebPushSubscriptionRecord: ...
