"""Shared Web Push subscription persistence primitives."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta

import my_lib.sqlite_util
import my_lib.time
from ._webpush_store_types import (
    DeliveryLogEntry,
    DeliveryStatus,
    LockingMode,
    SubscriptionFactory,
    WebPushSubscriptionRecord,
)

logger = logging.getLogger(__name__)

class BaseWebPushStore:
    """SQLite-backed Web Push subscription store with configurable group column."""

    def __init__(
        self,
        db_path: pathlib.Path,
        schema_dir: pathlib.Path,
        *,
        group_filter_column: str,
        legacy_group_filter_columns: Iterable[str] = (),
        legacy_product_filter_columns: Iterable[str] = (),
        locking_mode: LockingMode = "NORMAL",
        subscription_factory: SubscriptionFactory | None = None,
    ):
        self._db_path = db_path
        self._schema_dir = schema_dir
        self._group_filter_column = group_filter_column
        self._legacy_group_filter_columns = tuple(legacy_group_filter_columns)
        self._legacy_product_filter_columns = tuple(legacy_product_filter_columns)
        self._locking_mode = locking_mode
        self._subscription_factory = subscription_factory or WebPushSubscriptionRecord
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        schema_path = self._schema_dir / "sqlite_webpush.schema"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        my_lib.sqlite_util.init_schema_from_file(
            self._db_path,
            schema_path,
            locking_mode=self._locking_mode,
        )
        self._migrate_db()

    def _migrate_db(self) -> None:
        with self._get_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(webpush_subscriptions)")}

            if self._group_filter_column not in columns:
                for legacy_column in self._legacy_group_filter_columns:
                    if legacy_column in columns:
                        conn.execute(
                            f"ALTER TABLE webpush_subscriptions RENAME COLUMN {legacy_column} TO {self._group_filter_column}"
                        )
                        logger.info(
                            "Migrated webpush_subscriptions: %s -> %s",
                            legacy_column,
                            self._group_filter_column,
                        )
                        break

            if "product_filter" not in columns:
                for legacy_column in self._legacy_product_filter_columns:
                    if legacy_column in columns:
                        conn.execute(
                            f"ALTER TABLE webpush_subscriptions RENAME COLUMN {legacy_column} TO product_filter"
                        )
                        logger.info(
                            "Migrated webpush_subscriptions: %s -> product_filter",
                            legacy_column,
                        )
                        break

            conn.commit()

    @contextmanager
    def _get_connection(self) -> sqlite3.Connection:
        with my_lib.sqlite_util.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def save_subscription(
        self,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        *,
        group_filter: list[str] | None = None,
        event_type_filter: list[str] | None = None,
        product_filter: list[str] | None = None,
    ) -> int:
        group_json = json.dumps(group_filter) if group_filter else None
        event_json = json.dumps(event_type_filter) if event_type_filter else None
        product_json = json.dumps(product_filter) if product_filter else None
        now = my_lib.time.now()

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE webpush_subscriptions
                SET p256dh_key = ?, auth_key = ?, {self._group_filter_column} = ?, event_type_filter = ?,
                    product_filter = ?, is_active = TRUE, last_used_at = ?
                WHERE endpoint = ?
                """,
                (p256dh_key, auth_key, group_json, event_json, product_json, now.isoformat(), endpoint),
            )
            if cursor.rowcount > 0:
                row = conn.execute(
                    "SELECT id FROM webpush_subscriptions WHERE endpoint = ?",
                    (endpoint,),
                ).fetchone()
                conn.commit()
                return row["id"] if row else 0

            cursor = conn.execute(
                f"""
                INSERT INTO webpush_subscriptions
                    (endpoint, p256dh_key, auth_key, {self._group_filter_column}, event_type_filter,
                     product_filter, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)
                """,
                (endpoint, p256dh_key, auth_key, group_json, event_json, product_json, now.isoformat()),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_subscription_by_endpoint(self, endpoint: str) -> WebPushSubscriptionRecord | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            return self._row_to_subscription(row) if row is not None else None

    def get_subscription_by_id(self, subscription_id: int) -> WebPushSubscriptionRecord | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM webpush_subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            return self._row_to_subscription(row) if row is not None else None

    def update_filters(
        self,
        endpoint: str,
        *,
        group_filter: list[str] | None,
        event_type_filter: list[str] | None,
        product_filter: list[str] | None = None,
    ) -> bool:
        group_json = json.dumps(group_filter) if group_filter else None
        event_json = json.dumps(event_type_filter) if event_type_filter else None
        product_json = json.dumps(product_filter) if product_filter else None

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE webpush_subscriptions
                SET {self._group_filter_column} = ?, event_type_filter = ?, product_filter = ?
                WHERE endpoint = ?
                """,
                (group_json, event_json, product_json, endpoint),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_product_filter(self, endpoint: str, product_id: str, subscribe: bool) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT product_filter FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            if row is None:
                return False

            current_filter = json.loads(row["product_filter"]) if row["product_filter"] else []
            if subscribe:
                if product_id not in current_filter:
                    current_filter.append(product_id)
            elif product_id in current_filter:
                current_filter.remove(product_id)

            product_json = json.dumps(current_filter) if current_filter else None
            cursor = conn.execute(
                "UPDATE webpush_subscriptions SET product_filter = ? WHERE endpoint = ?",
                (product_json, endpoint),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_subscription(self, endpoint: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_active_subscriptions_for_event(
        self,
        *,
        group: str | None,
        event_type: str | None,
        product_id: str | None = None,
    ) -> list[WebPushSubscriptionRecord]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM webpush_subscriptions WHERE is_active = TRUE").fetchall()

        subscriptions: list[WebPushSubscriptionRecord] = []
        for row in rows:
            subscription = self._row_to_subscription(row)

            if product_id and subscription.product_filter and product_id in subscription.product_filter:
                subscriptions.append(subscription)
                continue

            if (
                subscription.group_filter is not None
                and group is not None
                and group not in subscription.group_filter
            ):
                continue

            if (
                subscription.event_type_filter is not None
                and event_type is not None
                and event_type not in subscription.event_type_filter
            ):
                continue

            subscriptions.append(subscription)

        return subscriptions

    def get_all_active_subscriptions(self) -> list[WebPushSubscriptionRecord]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM webpush_subscriptions WHERE is_active = TRUE").fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def get_subscription_count(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM webpush_subscriptions WHERE is_active = TRUE"
            ).fetchone()
        return row[0] if row else 0

    def update_last_used(self, subscription_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE webpush_subscriptions SET last_used_at = ? WHERE id = ?",
                (my_lib.time.now().isoformat(), subscription_id),
            )
            conn.commit()

    def mark_expired(self, endpoint: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE webpush_subscriptions SET is_active = FALSE WHERE endpoint = ?",
                (endpoint,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_inactive_subscriptions(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM webpush_subscriptions WHERE is_active = FALSE")
            conn.commit()
            return cursor.rowcount

    def log_delivery(
        self,
        subscription_id: int,
        event_id: int,
        status: DeliveryStatus,
        error_message: str | None = None,
    ) -> int:
        now = my_lib.time.now()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO webpush_delivery_logs
                    (subscription_id, event_id, status, sent_at, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (subscription_id, event_id, status.value, now.isoformat(), error_message),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_delivery_logs(self, subscription_id: int, limit: int = 100) -> list[DeliveryLogEntry]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM webpush_delivery_logs
                WHERE subscription_id = ?
                ORDER BY sent_at DESC
                LIMIT ?
                """,
                (subscription_id, limit),
            ).fetchall()
        return [self._row_to_delivery_log(row) for row in rows]

    def get_delivery_stats(self, days: int = 30) -> dict[str, int]:
        since = my_lib.time.now() - timedelta(days=days)
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM webpush_delivery_logs
                WHERE sent_at >= ?
                GROUP BY status
                """,
                ((since - datetime.resolution).isoformat(),),
            ).fetchall()

        stats = {"total": 0, "sent": 0, "failed": 0, "expired": 0}
        for row in rows:
            count = row["count"]
            stats[row["status"]] = count
            stats["total"] += count
        return stats

    def get_last_delivery_time(self) -> datetime | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT MAX(sent_at) as last_sent FROM webpush_delivery_logs"
            ).fetchone()
        if row is None or row["last_sent"] is None:
            return None
        return datetime.fromisoformat(row["last_sent"])

    def get_group_subscription_stats(self) -> dict[str, int]:
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT {self._group_filter_column} FROM webpush_subscriptions WHERE is_active = TRUE"
            ).fetchall()

        stats: dict[str, int] = {"all": 0}
        for row in rows:
            group_filter = row[self._group_filter_column]
            if group_filter is None:
                stats["all"] += 1
                continue
            for group in json.loads(group_filter):
                stats[group] = stats.get(group, 0) + 1
        return stats

    def get_product_subscription_stats(self) -> dict[str, int]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT product_filter FROM webpush_subscriptions
                WHERE is_active = TRUE AND product_filter IS NOT NULL
                """
            ).fetchall()

        product_counts: dict[str, int] = {}
        for row in rows:
            product_filter = row["product_filter"]
            if not product_filter:
                continue
            for product_id in json.loads(product_filter):
                product_counts[product_id] = product_counts.get(product_id, 0) + 1
        return product_counts

    def _row_to_subscription(self, row: sqlite3.Row) -> WebPushSubscriptionRecord:
        group_filter = json.loads(row[self._group_filter_column]) if row[self._group_filter_column] else None
        event_type_filter = json.loads(row["event_type_filter"]) if row["event_type_filter"] else None
        product_filter = json.loads(row["product_filter"]) if row["product_filter"] else None
        last_used_at = datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
        return self._subscription_factory(
            id=row["id"],
            endpoint=row["endpoint"],
            p256dh_key=row["p256dh_key"],
            auth_key=row["auth_key"],
            group_filter=group_filter,
            event_type_filter=event_type_filter,
            product_filter=product_filter,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used_at=last_used_at,
            is_active=bool(row["is_active"]),
        )

    def _row_to_delivery_log(self, row: sqlite3.Row) -> DeliveryLogEntry:
        return DeliveryLogEntry(
            id=row["id"],
            subscription_id=row["subscription_id"],
            event_id=row["event_id"],
            status=DeliveryStatus(row["status"]),
            sent_at=datetime.fromisoformat(row["sent_at"]),
            error_message=row["error_message"],
        )
