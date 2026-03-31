from __future__ import annotations

import pathlib
import sqlite3

from price_platform.notification.webpush_store import BaseWebPushStore
from price_platform.schema_registry import bundled_schema_dir, resolve_schema_path
from price_platform.store.price_event_store import BasePriceEventStore


def _write_schema(path: pathlib.Path, sql: str) -> None:
    path.write_text(sql, encoding="utf-8")


def test_price_event_store_canonicalizes_selection_column_once(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / "events.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE price_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                priority INTEGER,
                product_id TEXT,
                store TEXT,
                price INTEGER,
                url TEXT,
                previous_price INTEGER,
                reference_price INTEGER,
                change_percent REAL,
                period_days INTEGER,
                color_key TEXT,
                recorded_at TEXT,
                suppressed INTEGER DEFAULT 0,
                superseded_by INTEGER,
                twitter_posted INTEGER DEFAULT 0,
                twitter_enabled INTEGER DEFAULT 1
            );
            """
        )

    BasePriceEventStore(
        db_path=db_path,
        schema_dir=None,
        selection_column="color_key",
        event_factory=lambda row, selection: {"row": row, "selection": selection},
    )
    BasePriceEventStore(
        db_path=db_path,
        schema_dir=None,
        selection_column="color_key",
        event_factory=lambda row, selection: {"row": row, "selection": selection},
    )

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(price_events)").fetchall()}
        migrations = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}

    assert "selection_key" in columns
    assert "color_key" not in columns
    assert "canonicalize-price-events-selection" in migrations


def test_webpush_store_renames_legacy_columns(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / "webpush.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE webpush_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT UNIQUE,
                p256dh_key TEXT,
                auth_key TEXT,
                maker_filter TEXT,
                item_filter TEXT,
                event_type_filter TEXT,
                created_at TEXT,
                last_used_at TEXT,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE webpush_delivery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER,
                endpoint TEXT,
                status TEXT,
                event_type TEXT,
                product_id TEXT,
                sent_at TEXT,
                detail TEXT
            );
            """
        )

    BaseWebPushStore(
        db_path=db_path,
        schema_dir=None,
        group_filter_column="maker_filter",
        legacy_group_filter_columns=(),
        legacy_product_filter_columns=("item_filter",),
    )

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(webpush_subscriptions)").fetchall()}
        migrations = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}

    assert "group_filter" in columns
    assert "product_filter" in columns
    assert "maker_filter" not in columns
    assert "item_filter" not in columns
    assert "canonicalize-webpush-filters" in migrations


def test_schema_registry_prefers_override_but_has_bundled_defaults(tmp_path: pathlib.Path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    override_path = schema_dir / "sqlite_notification.schema"
    _write_schema(override_path, "CREATE TABLE IF NOT EXISTS override_marker (id INTEGER);")

    assert resolve_schema_path("sqlite_notification.schema", schema_dir=schema_dir) == override_path
    assert resolve_schema_path("sqlite_notification.schema") == bundled_schema_dir() / "sqlite_notification.schema"
