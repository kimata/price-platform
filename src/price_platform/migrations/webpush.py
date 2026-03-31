"""Migrations for the shared webpush store."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable

from price_platform.sqlite_store import Migration

logger = logging.getLogger(__name__)

CANONICAL_GROUP_FILTER_COLUMN = "group_filter"
CANONICAL_PRODUCT_FILTER_COLUMN = "product_filter"


def build_webpush_migrations(
    *,
    group_filter_column: str,
    legacy_group_filter_columns: Iterable[str] = (),
    legacy_product_filter_columns: Iterable[str] = (),
) -> tuple[Migration, ...]:
    group_candidates = []
    if group_filter_column != CANONICAL_GROUP_FILTER_COLUMN:
        group_candidates.append(group_filter_column)
    group_candidates.extend(legacy_group_filter_columns)

    return (
        Migration(
            name="canonicalize-webpush-filters",
            apply=lambda conn: _canonicalize_webpush_columns(
                conn,
                legacy_group_filter_columns=tuple(dict.fromkeys(group_candidates)),
                legacy_product_filter_columns=tuple(dict.fromkeys(legacy_product_filter_columns)),
            ),
        ),
    )


def _canonicalize_webpush_columns(
    conn: sqlite3.Connection,
    *,
    legacy_group_filter_columns: tuple[str, ...],
    legacy_product_filter_columns: tuple[str, ...],
) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(webpush_subscriptions)")}

    if CANONICAL_GROUP_FILTER_COLUMN not in columns:
        for legacy_column in legacy_group_filter_columns:
            if legacy_column in columns:
                conn.execute(
                    f"ALTER TABLE webpush_subscriptions RENAME COLUMN {legacy_column} TO {CANONICAL_GROUP_FILTER_COLUMN}"  # noqa: S608
                )
                logger.info(
                    "Migrated webpush_subscriptions: %s -> %s",
                    legacy_column,
                    CANONICAL_GROUP_FILTER_COLUMN,
                )
                columns.remove(legacy_column)
                columns.add(CANONICAL_GROUP_FILTER_COLUMN)
                break
    if CANONICAL_GROUP_FILTER_COLUMN not in columns:
        conn.execute(
            f"ALTER TABLE webpush_subscriptions ADD COLUMN {CANONICAL_GROUP_FILTER_COLUMN} TEXT"  # noqa: S608
        )
        logger.info("Migrated webpush_subscriptions: added %s column", CANONICAL_GROUP_FILTER_COLUMN)

    if CANONICAL_PRODUCT_FILTER_COLUMN not in columns:
        for legacy_column in legacy_product_filter_columns:
            if legacy_column in columns:
                conn.execute(
                    f"ALTER TABLE webpush_subscriptions RENAME COLUMN {legacy_column} TO {CANONICAL_PRODUCT_FILTER_COLUMN}"  # noqa: S608
                )
                logger.info(
                    "Migrated webpush_subscriptions: %s -> %s",
                    legacy_column,
                    CANONICAL_PRODUCT_FILTER_COLUMN,
                )
                columns.remove(legacy_column)
                columns.add(CANONICAL_PRODUCT_FILTER_COLUMN)
                break
    if CANONICAL_PRODUCT_FILTER_COLUMN not in columns:
        conn.execute(
            f"ALTER TABLE webpush_subscriptions ADD COLUMN {CANONICAL_PRODUCT_FILTER_COLUMN} TEXT"  # noqa: S608
        )
        logger.info("Migrated webpush_subscriptions: added %s column", CANONICAL_PRODUCT_FILTER_COLUMN)
