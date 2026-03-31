"""Migrations for the shared price-events store."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from price_platform.sqlite_store import Migration

logger = logging.getLogger(__name__)

CANONICAL_SELECTION_COLUMN = "selection_key"


def build_price_event_migrations(
    *,
    selection_column: str | None,
    pre_schema_migrate: Callable[[sqlite3.Connection], None] | None = None,
) -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    if pre_schema_migrate is not None:
        migrations.append(Migration(name="legacy-pre-schema-migrate", apply=pre_schema_migrate))
    if selection_column is not None:
        migrations.append(
            Migration(
                name="canonicalize-price-events-selection",
                apply=lambda conn, legacy_column=selection_column: _canonicalize_selection_column(conn, legacy_column),
            )
        )
    return tuple(migrations)


def _canonicalize_selection_column(conn: sqlite3.Connection, legacy_column: str) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(price_events)").fetchall()}
    if CANONICAL_SELECTION_COLUMN in columns:
        return
    if legacy_column in columns:
        conn.execute(
            f"ALTER TABLE price_events RENAME COLUMN {legacy_column} TO {CANONICAL_SELECTION_COLUMN}"  # noqa: S608
        )
        logger.info("Migrated price_events: %s -> %s", legacy_column, CANONICAL_SELECTION_COLUMN)
        return
    conn.execute(f"ALTER TABLE price_events ADD COLUMN {CANONICAL_SELECTION_COLUMN} TEXT")  # noqa: S608
    logger.info("Migrated price_events: added %s column", CANONICAL_SELECTION_COLUMN)
