"""Client metrics schema migrations owned by price-platform."""

from __future__ import annotations

import sqlite3

from ..sqlite_store import Migration


def _create_social_referral_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS social_referral_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            event_name TEXT NOT NULL,
            source TEXT NOT NULL,
            medium TEXT,
            campaign TEXT,
            post_variant TEXT,
            post_id TEXT,
            social_event TEXT,
            session_id TEXT NOT NULL,
            landing_path TEXT NOT NULL,
            page_path TEXT NOT NULL,
            referrer TEXT,
            page_depth INTEGER NOT NULL DEFAULT 1,
            device_type TEXT NOT NULL,
            user_agent TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_social_referral_recorded
            ON social_referral_events(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_social_referral_variant
            ON social_referral_events(post_variant, event_name, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_social_referral_session
            ON social_referral_events(session_id, recorded_at);
        """
    )
    conn.commit()


def build_client_metrics_migrations() -> tuple[Migration, ...]:
    """Build client metrics migrations."""
    return (
        Migration(
            name="001_social_referral_events",
            apply=_create_social_referral_tables,
        ),
    )
