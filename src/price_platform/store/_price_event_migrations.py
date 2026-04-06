"""SQLite migrations for price event storage."""

from __future__ import annotations

import sqlite3

from price_platform.sqlite_store import Migration


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _add_price_event_stat_columns(conn: sqlite3.Connection) -> None:
    columns = (
        ("percentile_rank", "percentile_rank REAL"),
        ("rarity_tier", "rarity_tier TEXT"),
        ("baseline_price", "baseline_price INTEGER"),
        ("sample_days", "sample_days INTEGER"),
        ("sample_count", "sample_count INTEGER"),
        ("rarity_window_days", "rarity_window_days INTEGER"),
        ("detector_version", "detector_version TEXT"),
        ("canonical_variant_key", "canonical_variant_key TEXT"),
        ("event_family", "event_family TEXT"),
        ("comparison_basis", "comparison_basis TEXT"),
        ("severity", "severity TEXT"),
    )
    for column_name, ddl in columns:
        _add_column_if_missing(conn, "price_events", column_name, ddl)
    conn.commit()


PRICE_EVENT_MIGRATIONS = (
    Migration(
        name="add-price-event-stat-columns",
        apply=_add_price_event_stat_columns,
    ),
)

