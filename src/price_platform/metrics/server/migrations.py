"""SQLite migrations for crawl metrics storage.

スキーマ適用は CREATE TABLE IF NOT EXISTS のみのため、後から追加された列は
既存 DB に反映されない。読み取り側は row_dict.get() で防御できるが、
書き込み側 (increment_round_count 等) は旧 DB で OperationalError になる (B7)。
列追加をマイグレーションとして表現し、旧 DB を確実に収束させる。
"""

from __future__ import annotations

import sqlite3

from ...sqlite_store import Migration


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _add_crawl_session_columns(conn: sqlite3.Connection) -> None:
    columns = (
        ("last_heartbeat_at", "last_heartbeat_at TEXT"),
        ("work_ended_at", "work_ended_at TEXT"),
        ("round_count", "round_count INTEGER DEFAULT 0"),
        ("round_start_product_count", "round_start_product_count INTEGER DEFAULT 0"),
        ("round_start_store_count", "round_start_store_count INTEGER DEFAULT 0"),
        ("last_round_completed_at", "last_round_completed_at TEXT"),
        ("exit_reason", "exit_reason TEXT"),
    )
    for column_name, ddl in columns:
        _add_column_if_missing(conn, "crawl_sessions", column_name, ddl)
    conn.commit()


METRICS_MIGRATIONS = (
    Migration(name="add-crawl-session-columns", apply=_add_crawl_session_columns),
)
