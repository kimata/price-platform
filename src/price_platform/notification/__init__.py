"""Notification modules for price-platform applications.

Provides shared notification queue persistence and Twitter posting
for crawl-based price tracking applications.
"""

from .notification_store import (
    NotificationItem,
    NotificationStatus,
    NotificationStore,
    RateLimitState,
    get_notification_store,
    init_notification_store,
    open_existing_notification_store,
    open_notification_store,
)
from .twitter_poster import (
    TwitterConfig,
    TwitterPoster,
    TwitterRateLimit,
)

__all__ = [
    "NotificationItem",
    "NotificationStatus",
    "NotificationStore",
    "RateLimitState",
    "TwitterConfig",
    "TwitterPoster",
    "TwitterRateLimit",
    "get_notification_store",
    "init_notification_store",
    "open_existing_notification_store",
    "open_notification_store",
]
