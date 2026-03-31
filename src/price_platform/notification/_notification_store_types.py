"""Types shared by the notification queue store."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol

LockingMode = Literal["NORMAL", "EXCLUSIVE"]


class SupportsNotificationStoreConfig(Protocol):
    notification: Any

    @property
    def schema_dir(self) -> pathlib.Path: ...

    def get_absolute_path(self, relative_path: pathlib.Path) -> pathlib.Path: ...


class NotificationStatus(Enum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class NotificationItem:
    id: int
    event_id: int
    event_type: str
    product_id: str
    store: str
    price: int
    url: str | None
    message: str
    created_at: datetime
    status: NotificationStatus
    posted_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0


@dataclass(frozen=True)
class RateLimitState:
    next_available_at: datetime
    recorded_at: datetime
    app_reset: datetime
    user_reset: datetime
