"""Notification modules for price-platform applications.

Provides shared notification queue persistence and Twitter posting
for crawl-based price tracking applications.
"""

from ..config.models import TwitterConfig
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
from .webpush_sender import BaseWebPushSender, WebPushResult, build_detail_url
from .webpush_store import BaseWebPushStore, DeliveryLogEntry, DeliveryStatus, WebPushSubscriptionRecord
from .twitter_poster import (
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
    "BaseWebPushSender",
    "BaseWebPushStore",
    "DeliveryLogEntry",
    "DeliveryStatus",
    "WebPushResult",
    "WebPushSubscriptionRecord",
    "build_detail_url",
    "get_notification_store",
    "init_notification_store",
    "open_existing_notification_store",
    "open_notification_store",
]
