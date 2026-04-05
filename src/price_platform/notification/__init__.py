"""Notification modules for price-platform applications.

Provides shared notification queue persistence and Twitter posting
for crawl-based price tracking applications.
"""

from ..config.models import TwitterConfig
from .manager import (
    BaseNotificationManager,
    NotificationPresentation,
    NotificationRuntime,
    build_twitter_config,
)
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
    TwitterPoster,
    TwitterRateLimit,
)
from .webpush_sender import BaseWebPushSender, WebPushResult, build_detail_url
from .webpush_store import BaseWebPushStore, DeliveryLogEntry, DeliveryStatus, WebPushSubscriptionRecord

__all__ = [
    "BaseNotificationManager",
    "BaseWebPushSender",
    "BaseWebPushStore",
    "DeliveryLogEntry",
    "DeliveryStatus",
    "NotificationItem",
    "NotificationPresentation",
    "NotificationRuntime",
    "NotificationStatus",
    "NotificationStore",
    "RateLimitState",
    "TwitterConfig",
    "TwitterPoster",
    "TwitterRateLimit",
    "WebPushResult",
    "WebPushSubscriptionRecord",
    "build_detail_url",
    "build_twitter_config",
    "get_notification_store",
    "init_notification_store",
    "open_existing_notification_store",
    "open_notification_store",
]
