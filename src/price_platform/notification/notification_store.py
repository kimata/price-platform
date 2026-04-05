"""Notification queue persistence for price-platform applications."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from price_platform.schema_registry import resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase

from ._notification_payload import NotificationPayload, SupportsNotificationEvent, build_notification_payload
from ._notification_posting_history_repository import (
    get_last_posted_time as repo_get_last_posted_time,
    get_last_posted_time_for_product as repo_get_last_posted_time_for_product,
)
from ._notification_queue_repository import (
    cleanup_old_items as repo_cleanup_old_items,
    enqueue_notification,
    get_pending_count as repo_get_pending_count,
    get_pending_notifications,
    increment_retry_count as repo_increment_retry_count,
    mark_failed as repo_mark_failed,
    mark_posted as repo_mark_posted,
    mark_skipped as repo_mark_skipped,
    reset_to_pending as repo_reset_to_pending,
    trim_pending_keep_latest as repo_trim_pending_keep_latest,
)
from ._notification_rate_limit_repository import (
    clear_rate_limit_state as repo_clear_rate_limit_state,
    get_rate_limit_state as repo_get_rate_limit_state,
    save_rate_limit_state as repo_save_rate_limit_state,
)
from ._notification_store_types import (
    LockingMode,
    NotificationItem,
    NotificationStatus,
    RateLimitState,
    SupportsNotificationStoreConfig,
)

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class NotificationStore(SQLiteStoreBase):
    """SQLite-based notification queue store."""

    def __init__(
        self,
        db_path: pathlib.Path,
        *,
        locking_mode: LockingMode = "NORMAL",
    ):
        super().__init__(
            db_path=db_path,
            schema_path=resolve_schema_path("sqlite_notification.schema"),
            locking_mode=locking_mode,
        )

    @contextmanager
    def _get_connection(self) -> AbstractContextManager[sqlite3.Connection]:
        with self.connection() as conn:
            yield conn

    def enqueue(
        self,
        event_or_payload: NotificationPayload | SupportsNotificationEvent,
        message: str | None = None,
        max_pending: int = 10,
    ) -> int:
        """Add a notification to the queue."""
        payload = build_notification_payload(event_or_payload, message)
        with self._get_connection() as conn:
            queue_id = enqueue_notification(conn, payload)
            logger.debug("Enqueued notification: id=%d, product=%s", queue_id, payload.product_id)

        skipped = self.trim_pending_keep_latest(max_pending)
        if skipped > 0:
            logger.info(
                "キュー上限超過のため古い通知をスキップ: %d件スキップ、%d件保持",
                skipped,
                max_pending,
            )
        return queue_id

    def get_pending(self, limit: int = 10) -> list[NotificationItem]:
        with self._get_connection() as conn:
            return get_pending_notifications(conn, limit=limit)

    def get_next_pending(self) -> NotificationItem | None:
        items = self.get_pending(limit=1)
        return items[0] if items else None

    def mark_posted(self, item_id: int, tweet_id: str | None = None) -> None:
        with self._get_connection() as conn:
            repo_mark_posted(conn, item_id, tweet_id=tweet_id)
            logger.info("Marked notification as posted: id=%d", item_id)

    def mark_failed(self, item_id: int, error_message: str) -> None:
        with self._get_connection() as conn:
            repo_mark_failed(conn, item_id, error_message)
            logger.warning("Marked notification as failed: id=%d, error=%s", item_id, error_message)

    def mark_skipped(self, item_id: int, reason: str) -> None:
        with self._get_connection() as conn:
            repo_mark_skipped(conn, item_id, reason)
            logger.info("Marked notification as skipped: id=%d, reason=%s", item_id, reason)

    def reset_to_pending(self, item_id: int) -> None:
        with self._get_connection() as conn:
            repo_reset_to_pending(conn, item_id)

    def increment_retry_count(self, item_id: int, error_message: str) -> int:
        with self._get_connection() as conn:
            return repo_increment_retry_count(conn, item_id, error_message)

    def get_last_posted_time(self) -> datetime | None:
        with self._get_connection() as conn:
            return repo_get_last_posted_time(conn)

    def get_last_posted_time_for_product(self, product_id: str) -> datetime | None:
        with self._get_connection() as conn:
            return repo_get_last_posted_time_for_product(conn, product_id)

    def get_pending_count(self) -> int:
        with self._get_connection() as conn:
            return repo_get_pending_count(conn)

    def trim_pending_keep_latest(self, keep_count: int = 10) -> int:
        with self._get_connection() as conn:
            return repo_trim_pending_keep_latest(conn, keep_count=keep_count)

    def cleanup_old_items(self, days: int = 30) -> int:
        with self._get_connection() as conn:
            deleted = repo_cleanup_old_items(conn, days=days)
            if deleted > 0:
                logger.info("Deleted %d old notification items", deleted)
            return deleted

    def save_rate_limit_state(
        self,
        next_available_at: datetime,
        app_reset: datetime,
        user_reset: datetime,
    ) -> None:
        with self._get_connection() as conn:
            repo_save_rate_limit_state(
                conn,
                next_available_at=next_available_at,
                app_reset=app_reset,
                user_reset=user_reset,
            )
            logger.info(
                "Saved rate limit state: next_available_at=%s",
                next_available_at.strftime("%m/%d %H:%M"),
            )

    def get_rate_limit_state(self) -> RateLimitState | None:
        with self._get_connection() as conn:
            return repo_get_rate_limit_state(conn)

    def clear_rate_limit_state(self) -> None:
        with self._get_connection() as conn:
            repo_clear_rate_limit_state(conn)
            logger.debug("Cleared rate limit state")


def open_notification_store(db_path: pathlib.Path) -> NotificationStore:
    """Create a notification store without touching any global singleton."""
    return NotificationStore(db_path)


def open_existing_notification_store(config: SupportsNotificationStoreConfig) -> NotificationStore | None:
    """Open the configured notification store only when it already exists."""
    notification_config = getattr(config, "notification", None)
    if notification_config is None or not notification_config.enabled:
        return None

    db_path = config.get_absolute_path(notification_config.db_path)
    if not db_path.exists():
        return None
    return open_notification_store(db_path)


_notification_store: NotificationStore | None = None


def get_notification_store() -> NotificationStore:
    if _notification_store is None:
        raise RuntimeError("NotificationStore not initialized. Call init_notification_store() first.")
    return _notification_store


def init_notification_store(db_path: pathlib.Path) -> NotificationStore:
    global _notification_store
    _notification_store = NotificationStore(db_path)
    return _notification_store


def _reset_notification_store() -> None:
    global _notification_store
    _notification_store = None
