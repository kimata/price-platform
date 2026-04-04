from __future__ import annotations

import pathlib
import sqlite3

from price_platform.notification.webpush_store import BaseWebPushStore
from price_platform.schema_registry import bundled_schema_dir, resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase
from price_platform.store.price_event_store import BasePriceEventStore


def _write_schema(path: pathlib.Path, sql: str) -> None:
    path.write_text(sql, encoding="utf-8")


def test_price_event_store_uses_canonical_schema_without_compat_migrations(tmp_path: pathlib.Path) -> None:
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
                selection_key TEXT,
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
        selection_column="variant_id",
        event_factory=lambda row, selection: {"row": row, "selection": selection},
    )
    BasePriceEventStore(
        db_path=db_path,
        selection_column="variant_id",
        event_factory=lambda row, selection: {"row": row, "selection": selection},
    )

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(price_events)").fetchall()}
        migrations = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        metadata = dict(conn.execute("SELECT key, value FROM schema_metadata").fetchall())

    assert "selection_key" in columns
    assert "canonicalize-price-events-selection" not in migrations
    assert metadata["schema_name"] == "sqlite_price_events.schema"
    assert metadata["schema_sha256"]


def test_webpush_store_uses_canonical_schema_without_compat_migrations(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / "webpush.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE webpush_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT UNIQUE,
                p256dh_key TEXT,
                auth_key TEXT,
                group_filter TEXT,
                product_filter TEXT,
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

    BaseWebPushStore(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(webpush_subscriptions)").fetchall()}
        migrations = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        metadata = dict(conn.execute("SELECT key, value FROM schema_metadata").fetchall())

    assert "group_filter" in columns
    assert "product_filter" in columns
    assert "canonicalize-webpush-filters" not in migrations
    assert metadata["schema_name"] == "sqlite_webpush.schema"
    assert metadata["schema_sha256"]


def test_schema_registry_resolves_bundled_schema() -> None:
    assert resolve_schema_path("sqlite_notification.schema") == bundled_schema_dir() / "sqlite_notification.schema"


def test_sqlite_store_base_can_delay_initialization(tmp_path: pathlib.Path) -> None:
    schema_path = tmp_path / "dummy.schema"
    _write_schema(schema_path, "CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY);")
    db_path = tmp_path / "dummy.db"

    class _DummyStore(SQLiteStoreBase):
        pass

    store = _DummyStore(
        db_path=db_path,
        schema_path=schema_path,
        auto_initialize=False,
    )

    assert not db_path.exists()

    store.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    assert "demo" in tables
    assert "schema_metadata" in tables
