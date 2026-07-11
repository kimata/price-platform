"""SQLite migrations for Web Push subscription storage."""

from __future__ import annotations

import sqlite3

from price_platform.sqlite_store import Migration


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_failure_count_column(conn: sqlite3.Connection) -> None:
    if "consecutive_failure_count" in _table_columns(conn, "webpush_subscriptions"):
        return
    conn.execute(
        "ALTER TABLE webpush_subscriptions ADD COLUMN consecutive_failure_count INTEGER NOT NULL DEFAULT 0"
    )
    conn.commit()


WEBPUSH_MIGRATIONS = (
    Migration(name="add-webpush-failure-count", apply=_add_failure_count_column),
)
