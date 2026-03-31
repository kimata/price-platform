"""Notification queue persistence for price-platform applications."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from price_platform.platform import clock
from price_platform.schema_registry import resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase
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
    """SQLite-based notification queue store.

    ``price-platform`` owns the canonical notification schema. A consuming
    application can still provide ``schema_dir`` as an override for tests or
    controlled migrations.
    """

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_dir: pathlib.Path | None,
        *,
        locking_mode: LockingMode = "NORMAL",
    ):
        """Initialize notification store.

        Args:
            db_path: Path to the notification database file
            schema_dir: Optional override path to the schema directory
            locking_mode: SQLite locking mode (NORMAL for concurrent read,
                EXCLUSIVE for single process)
        """
        super().__init__(
            db_path=db_path,
            schema_path=resolve_schema_path("sqlite_notification.schema", schema_dir=schema_dir),
            locking_mode=locking_mode,
        )

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection."""
        with self.connection() as conn:
            yield conn

    def enqueue(self, event: Any, message: str, max_pending: int = 10) -> int:
        """Add a notification to the queue.

        Args:
            event: A price event object with ``id``, ``event_type`` (enum
                with ``.value``), ``product_id``, ``store`` (enum with
                ``.value``), ``price``, and ``url`` attributes.
            message: Pre-formatted message for posting
            max_pending: Maximum number of pending items to keep

        Returns:
            The ID of the created queue item
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notification_queue
                    (event_id, event_type, product_id, store, price, url, message, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.event_type.value,
                    event.product_id,
                    event.store.value,
                    event.price,
                    event.url,
                    message,
                    NotificationStatus.PENDING.value,
                ),
            )
            conn.commit()
            queue_id = cursor.lastrowid or 0
            logger.debug("Enqueued notification: id=%d, product=%s", queue_id, event.product_id)

        skipped = self.trim_pending_keep_latest(max_pending)
        if skipped > 0:
            logger.info(
                "キュー上限超過のため古い通知をスキップ: %d件スキップ、%d件保持",
                skipped,
                max_pending,
            )

        return queue_id

    def get_pending(self, limit: int = 10) -> list[NotificationItem]:
        """Get pending notifications ordered by creation time.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of pending notification items
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM notification_queue
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (NotificationStatus.PENDING.value, limit),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_next_pending(self) -> NotificationItem | None:
        """Get the oldest pending notification.

        Returns:
            The oldest pending notification item, or None if queue is empty
        """
        items = self.get_pending(limit=1)
        return items[0] if items else None

    def mark_posted(self, item_id: int, tweet_id: str | None = None) -> None:
        """Mark a notification as successfully posted.

        Args:
            item_id: The notification queue item ID
            tweet_id: Optional Twitter tweet ID
        """
        now = clock.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE notification_queue
                SET status = ?, posted_at = ?
                WHERE id = ?
                """,
                (NotificationStatus.POSTED.value, now.isoformat(), item_id),
            )
            if tweet_id:
                conn.execute(
                    """
                    INSERT INTO posting_history (queue_id, posted_at, tweet_id)
                    VALUES (?, ?, ?)
                    """,
                    (item_id, now.isoformat(), tweet_id),
                )
            conn.commit()
            logger.info("Marked notification as posted: id=%d", item_id)

    def mark_failed(self, item_id: int, error_message: str) -> None:
        """Mark a notification as failed.

        Args:
            item_id: The notification queue item ID
            error_message: Error description
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE notification_queue
                SET status = ?, error_message = ?
                WHERE id = ?
                """,
                (NotificationStatus.FAILED.value, error_message, item_id),
            )
            conn.commit()
            logger.warning("Marked notification as failed: id=%d, error=%s", item_id, error_message)

    def mark_skipped(self, item_id: int, reason: str) -> None:
        """Mark a notification as skipped.

        Args:
            item_id: The notification queue item ID
            reason: Reason for skipping
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE notification_queue
                SET status = ?, error_message = ?
                WHERE id = ?
                """,
                (NotificationStatus.SKIPPED.value, reason, item_id),
            )
            conn.commit()
            logger.info("Marked notification as skipped: id=%d, reason=%s", item_id, reason)

    def reset_to_pending(self, item_id: int) -> None:
        """Reset a failed notification back to pending for retry.

        Args:
            item_id: The notification queue item ID
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE notification_queue
                SET status = ?, error_message = NULL
                WHERE id = ?
                """,
                (NotificationStatus.PENDING.value, item_id),
            )
            conn.commit()

    def increment_retry_count(self, item_id: int, error_message: str) -> int:
        """Increment retry count for a notification and return new count.

        Args:
            item_id: The notification queue item ID
            error_message: Error description

        Returns:
            The new retry count after incrementing
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE notification_queue
                SET retry_count = retry_count + 1, error_message = ?
                WHERE id = ?
                """,
                (error_message, item_id),
            )
            cursor = conn.execute(
                "SELECT retry_count FROM notification_queue WHERE id = ?",
                (item_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            return row["retry_count"] if row else 0

    def get_last_posted_time(self) -> datetime | None:
        """Get the timestamp of the most recent successful posting.

        Returns:
            Timestamp of the last posting, or None if no posts exist
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT posted_at FROM posting_history
                ORDER BY posted_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row and row["posted_at"]:
                return datetime.fromisoformat(row["posted_at"])
            return None

    def get_last_posted_time_for_product(self, product_id: str) -> datetime | None:
        """Get the timestamp of the most recent successful posting for a product.

        Args:
            product_id: The product ID to check

        Returns:
            Timestamp of the last posting for this product, or None
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT ph.posted_at
                FROM posting_history ph
                JOIN notification_queue nq ON ph.queue_id = nq.id
                WHERE nq.product_id = ?
                ORDER BY ph.posted_at DESC
                LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            if row and row["posted_at"]:
                return datetime.fromisoformat(row["posted_at"])
            return None

    def get_pending_count(self) -> int:
        """Get the number of pending notifications.

        Returns:
            Count of pending notifications
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM notification_queue WHERE status = ?",
                (NotificationStatus.PENDING.value,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def trim_pending_keep_latest(self, keep_count: int = 10) -> int:
        """Trim pending items, keeping only the latest N.

        Args:
            keep_count: Number of latest items to keep

        Returns:
            Number of items skipped
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id FROM notification_queue
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (NotificationStatus.PENDING.value, keep_count),
            )
            keep_ids = [row["id"] for row in cursor.fetchall()]

            if not keep_ids:
                return 0

            # placeholders are "?" repetitions only — safe from injection
            placeholders = ",".join("?" * len(keep_ids))
            cursor = conn.execute(
                f"""
                UPDATE notification_queue
                SET status = ?, error_message = ?
                WHERE status = ? AND id NOT IN ({placeholders})
                """,  # noqa: S608
                (
                    NotificationStatus.SKIPPED.value,
                    "レート制限によりスキップ",
                    NotificationStatus.PENDING.value,
                    *keep_ids,
                ),
            )
            skipped = cursor.rowcount
            conn.commit()
            return skipped

    def cleanup_old_items(self, days: int = 30) -> int:
        """Delete old completed/failed items from the queue.

        Args:
            days: Delete items older than this many days

        Returns:
            Number of deleted items
        """
        cutoff = clock.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM notification_queue
                WHERE created_at < ? AND status IN (?, ?, ?)
                """,
                (
                    cutoff.isoformat(),
                    NotificationStatus.POSTED.value,
                    NotificationStatus.FAILED.value,
                    NotificationStatus.SKIPPED.value,
                ),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info("Deleted %d old notification items", deleted)
            return deleted

    def _row_to_item(self, row: sqlite3.Row) -> NotificationItem:
        """Convert database row to NotificationItem."""
        posted_at = None
        if row["posted_at"]:
            posted_at = datetime.fromisoformat(row["posted_at"])

        return NotificationItem(
            id=row["id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            product_id=row["product_id"],
            store=row["store"],
            price=row["price"],
            url=row["url"],
            message=row["message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=NotificationStatus(row["status"]),
            posted_at=posted_at,
            error_message=row["error_message"],
            retry_count=row["retry_count"],
        )

    def save_rate_limit_state(
        self,
        next_available_at: datetime,
        app_reset: datetime,
        user_reset: datetime,
    ) -> None:
        """Save rate limit state for persistence across restarts.

        Args:
            next_available_at: When posting becomes available
            app_reset: App rate limit reset time
            user_reset: User rate limit reset time
        """
        now = clock.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rate_limit_state
                    (id, next_available_at, recorded_at, app_reset, user_reset)
                VALUES (1, ?, ?, ?, ?)
                """,
                (
                    next_available_at.isoformat(),
                    now.isoformat(),
                    app_reset.isoformat(),
                    user_reset.isoformat(),
                ),
            )
            conn.commit()
            logger.info(
                "Saved rate limit state: next_available_at=%s",
                next_available_at.strftime("%m/%d %H:%M"),
            )

    def get_rate_limit_state(self) -> RateLimitState | None:
        """Get saved rate limit state.

        Returns:
            RateLimitState if exists, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM rate_limit_state WHERE id = 1")
            row = cursor.fetchone()
            if row is None:
                return None

            return RateLimitState(
                next_available_at=datetime.fromisoformat(row["next_available_at"]),
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                app_reset=datetime.fromisoformat(row["app_reset"]),
                user_reset=datetime.fromisoformat(row["user_reset"]),
            )

    def clear_rate_limit_state(self) -> None:
        """Clear saved rate limit state."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM rate_limit_state WHERE id = 1")
            conn.commit()
            logger.debug("Cleared rate limit state")


def open_notification_store(db_path: pathlib.Path, schema_dir: pathlib.Path | None = None) -> NotificationStore:
    """Create a notification store without touching any global singleton."""
    return NotificationStore(db_path, schema_dir)


def open_existing_notification_store(config: SupportsNotificationStoreConfig) -> NotificationStore | None:
    """Open the configured notification store only when it already exists."""
    notification_config = getattr(config, "notification", None)
    if notification_config is None or not notification_config.enabled:
        return None

    db_path = config.get_absolute_path(notification_config.db_path)
    if not db_path.exists():
        return None
    return open_notification_store(db_path)


# Global instance cache
_notification_store: NotificationStore | None = None


def get_notification_store() -> NotificationStore:
    """Get global notification store.

    Note: Must be initialized first by calling ``init_notification_store()``.
    """
    if _notification_store is None:
        raise RuntimeError("NotificationStore not initialized. Call init_notification_store() first.")
    return _notification_store


def init_notification_store(db_path: pathlib.Path, schema_dir: pathlib.Path | None = None) -> NotificationStore:
    """Initialize and return the global notification store.

    Args:
        db_path: Path to the notification database file
        schema_dir: Optional override path to the schema directory

    Returns:
        The initialized NotificationStore instance
    """
    global _notification_store
    _notification_store = NotificationStore(db_path, schema_dir)
    return _notification_store


def _reset_notification_store() -> None:
    """Reset notification store (for testing only)."""
    global _notification_store
    _notification_store = None
