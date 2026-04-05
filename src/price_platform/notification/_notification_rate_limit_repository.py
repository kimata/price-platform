"""Rate-limit state persistence helpers."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from price_platform.platform import clock

from ._notification_store_types import RateLimitState


def save_rate_limit_state(
    conn: sqlite3.Connection,
    *,
    next_available_at: datetime,
    app_reset: datetime,
    user_reset: datetime,
) -> None:
    now = clock.now()
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


def get_rate_limit_state(conn: sqlite3.Connection) -> RateLimitState | None:
    row = conn.execute("SELECT * FROM rate_limit_state WHERE id = 1").fetchone()
    if row is None:
        return None
    return RateLimitState(
        next_available_at=datetime.fromisoformat(row["next_available_at"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        app_reset=datetime.fromisoformat(row["app_reset"]),
        user_reset=datetime.fromisoformat(row["user_reset"]),
    )


def clear_rate_limit_state(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM rate_limit_state WHERE id = 1")
    conn.commit()
