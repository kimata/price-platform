"""Types shared by the Web Push subscription store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from price_platform.platform.sqlite import LockingMode as LockingMode


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
class DeliveryStats:
    """配信結果の期間集計。"""

    total: int = 0
    sent: int = 0
    failed: int = 0
    expired: int = 0


@dataclass(frozen=True)
class DeliveryDailyStats:
    """配信結果の日次集計 (F3: 配信成功率の推移可視化用)。"""

    date: str
    sent: int = 0
    failed: int = 0
    expired: int = 0

    @property
    def total(self) -> int:
        return self.sent + self.failed + self.expired

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 100.0
        return round(self.sent / self.total * 100, 1)


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
