"""Posting history queries for notification persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime


def get_last_posted_time(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        """
        SELECT posted_at FROM posting_history
        ORDER BY posted_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row and row["posted_at"]:
        return datetime.fromisoformat(row["posted_at"])
    return None


def get_last_posted_time_for_product(conn: sqlite3.Connection, product_id: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT ph.posted_at
        FROM posting_history ph
        JOIN notification_queue nq ON ph.queue_id = nq.id
        WHERE nq.product_id = ?
        ORDER BY ph.posted_at DESC
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if row and row["posted_at"]:
        return datetime.fromisoformat(row["posted_at"])
    return None
