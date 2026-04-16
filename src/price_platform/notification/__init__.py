"""Notification modules for price-platform applications.

Provides shared notification queue persistence and Twitter posting
for crawl-based price tracking applications.
"""

from ..config.models import TwitterConfig
from ._notification_payload import NotificationPayload
from .manager import (
    BaseNotificationManager,
    NotificationPresentation,
    NotificationRuntime,
    NotificationStrategies,
    ProductLineStrategy,
    SelectionKeyStrategy,
    SocialCopyStrategy,
    build_notification_runtime,
    build_social_message,
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
    "NotificationPayload",
    "NotificationPresentation",
    "NotificationRuntime",
    "NotificationStatus",
    "NotificationStore",
    "NotificationStrategies",
    "ProductLineStrategy",
    "RateLimitState",
    "SelectionKeyStrategy",
    "SocialCopyStrategy",
    "TwitterConfig",
    "TwitterPoster",
    "TwitterRateLimit",
    "WebPushResult",
    "WebPushSubscriptionRecord",
    "build_detail_url",
    "build_notification_runtime",
    "build_social_message",
    "build_twitter_config",
    "get_notification_store",
    "init_notification_store",
    "open_existing_notification_store",
    "open_notification_store",
]
