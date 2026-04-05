"""Queue repository helpers for notification persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from price_platform.platform import clock

from ._notification_payload import NotificationPayload
from ._notification_store_types import NotificationItem, NotificationStatus


def enqueue_notification(conn: sqlite3.Connection, payload: NotificationPayload) -> int:
    cursor = conn.execute(
        """
        INSERT INTO notification_queue
            (event_id, event_type, product_id, store, price, url, message, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.event_id,
            payload.event_type,
            payload.product_id,
            payload.store,
            payload.price,
            payload.url,
            payload.message,
            NotificationStatus.PENDING.value,
        ),
    )
    conn.commit()
    return cursor.lastrowid or 0


def row_to_notification_item(row: sqlite3.Row) -> NotificationItem:
    posted_at = datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None
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


def get_pending_notifications(conn: sqlite3.Connection, limit: int = 10) -> list[NotificationItem]:
    cursor = conn.execute(
        """
        SELECT * FROM notification_queue
        WHERE status = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (NotificationStatus.PENDING.value, limit),
    )
    return [row_to_notification_item(row) for row in cursor.fetchall()]


def mark_posted(conn: sqlite3.Connection, item_id: int, tweet_id: str | None = None) -> None:
    now = clock.now()
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


def mark_failed(conn: sqlite3.Connection, item_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE notification_queue
        SET status = ?, error_message = ?
        WHERE id = ?
        """,
        (NotificationStatus.FAILED.value, error_message, item_id),
    )
    conn.commit()


def mark_skipped(conn: sqlite3.Connection, item_id: int, reason: str) -> None:
    conn.execute(
        """
        UPDATE notification_queue
        SET status = ?, error_message = ?
        WHERE id = ?
        """,
        (NotificationStatus.SKIPPED.value, reason, item_id),
    )
    conn.commit()


def reset_to_pending(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute(
        """
        UPDATE notification_queue
        SET status = ?, error_message = NULL
        WHERE id = ?
        """,
        (NotificationStatus.PENDING.value, item_id),
    )
    conn.commit()


def increment_retry_count(conn: sqlite3.Connection, item_id: int, error_message: str) -> int:
    conn.execute(
        """
        UPDATE notification_queue
        SET retry_count = retry_count + 1, error_message = ?
        WHERE id = ?
        """,
        (error_message, item_id),
    )
    row = conn.execute(
        "SELECT retry_count FROM notification_queue WHERE id = ?",
        (item_id,),
    ).fetchone()
    conn.commit()
    return row["retry_count"] if row else 0


def get_pending_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM notification_queue WHERE status = ?",
        (NotificationStatus.PENDING.value,),
    ).fetchone()
    return row[0] if row else 0


def trim_pending_keep_latest(conn: sqlite3.Connection, keep_count: int = 10) -> int:
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


def cleanup_old_items(conn: sqlite3.Connection, days: int = 30) -> int:
    cutoff = clock.now() - timedelta(days=days)
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
    return deleted
