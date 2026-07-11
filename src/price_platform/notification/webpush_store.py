"""Shared Web Push subscription persistence primitives."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from datetime import datetime, timedelta

from price_platform.platform import clock
from price_platform.schema_registry import resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase

from ._webpush_migrations import WEBPUSH_MIGRATIONS
from ._webpush_store_types import (
    DeliveryDailyStats,
    DeliveryLogEntry,
    DeliveryStats,
    DeliveryStatus,
    LockingMode,
    SubscriptionFactory,
    WebPushSubscriptionRecord,
)

logger = logging.getLogger(__name__)

CANONICAL_GROUP_FILTER_COLUMN = "group_filter"
CANONICAL_PRODUCT_FILTER_COLUMN = "product_filter"

class BaseWebPushStore(SQLiteStoreBase):
    """SQLite-backed Web Push subscription store with configurable group column."""

    def __init__(
        self,
        db_path: pathlib.Path,
        *,
        locking_mode: LockingMode = "NORMAL",
        subscription_factory: SubscriptionFactory | None = None,
    ):
        self._group_filter_column = CANONICAL_GROUP_FILTER_COLUMN
        self._subscription_factory = subscription_factory or WebPushSubscriptionRecord
        super().__init__(
            db_path=db_path,
            schema_path=resolve_schema_path("sqlite_webpush.schema"),
            locking_mode=locking_mode,
            migrations=WEBPUSH_MIGRATIONS,
        )

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
        # 空リストは「何も受信しない」、None は「フィルタなし = 全受信」で意味が
        # 異なるため、falsy 判定で潰さず None のときだけ NULL を保存する (B3)。
        group_json = json.dumps(group_filter) if group_filter is not None else None
        event_json = json.dumps(event_type_filter) if event_type_filter is not None else None
        product_json = json.dumps(product_filter) if product_filter is not None else None
        now = clock.now()

        with self.connection() as conn:
            # UPDATE→INSERT の 2 段構えは並行リクエストで両方 INSERT に到達し
            # UNIQUE 制約違反になるため、単一のアトミックな upsert にする (B15)。
            conn.execute(
                f"""
                INSERT INTO webpush_subscriptions
                    (endpoint, p256dh_key, auth_key, {self._group_filter_column}, event_type_filter,
                     product_filter, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)
                ON CONFLICT(endpoint) DO UPDATE SET
                    p256dh_key = excluded.p256dh_key,
                    auth_key = excluded.auth_key,
                    {self._group_filter_column} = excluded.{self._group_filter_column},
                    event_type_filter = excluded.event_type_filter,
                    product_filter = excluded.product_filter,
                    is_active = TRUE,
                    last_used_at = ?
                """,  # noqa: S608 - 列名はクラス定数のみ埋め込み
                (
                    endpoint,
                    p256dh_key,
                    auth_key,
                    group_json,
                    event_json,
                    product_json,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            conn.commit()
            return row["id"] if row else 0

    def get_subscription_by_endpoint(self, endpoint: str) -> WebPushSubscriptionRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            return self._row_to_subscription(row) if row is not None else None

    def get_subscription_by_id(self, subscription_id: int) -> WebPushSubscriptionRecord | None:
        with self.connection() as conn:
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
        group_json = json.dumps(group_filter) if group_filter is not None else None
        event_json = json.dumps(event_type_filter) if event_type_filter is not None else None
        product_json = json.dumps(product_filter) if product_filter is not None else None

        with self.connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE webpush_subscriptions
                SET {self._group_filter_column} = ?, event_type_filter = ?, product_filter = ?
                WHERE endpoint = ?
                """,  # noqa: S608 - 列名はクラス定数のみ埋め込み
                (group_json, event_json, product_json, endpoint),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_product_filter(self, endpoint: str, product_id: str, subscribe: bool) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT product_filter FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            if row is None:
                return False

            current_filter = (
                json.loads(row[CANONICAL_PRODUCT_FILTER_COLUMN])
                if row[CANONICAL_PRODUCT_FILTER_COLUMN]
                else []
            )
            if subscribe:
                if product_id not in current_filter:
                    current_filter.append(product_id)
            elif product_id in current_filter:
                current_filter.remove(product_id)

            # 最後の 1 件を解除した場合も空リストとして保持する
            # (None に潰すと「フィルタなし = 全受信」に化ける)
            product_json = json.dumps(current_filter)
            cursor = conn.execute(
                f"UPDATE webpush_subscriptions SET {CANONICAL_PRODUCT_FILTER_COLUMN} = ? WHERE endpoint = ?",  # noqa: S608
                (product_json, endpoint),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_subscription(self, endpoint: str) -> bool:
        with self.connection() as conn:
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
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM webpush_subscriptions WHERE is_active = TRUE").fetchall()

        subscriptions: list[WebPushSubscriptionRecord] = []
        for row in rows:
            subscription = self._row_to_subscription(row)

            if subscription.product_filter is not None:
                if product_id is not None and product_id in subscription.product_filter:
                    subscriptions.append(subscription)
                    continue
                if subscription.group_filter is None:
                    # 商品指定のみの購読: リスト外の商品のイベントは受け取らない (B3)。
                    # group_filter も設定されている場合は OR 条件として group 判定へ進む。
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
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM webpush_subscriptions WHERE is_active = TRUE").fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def get_subscription_count(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM webpush_subscriptions WHERE is_active = TRUE").fetchone()
        return row[0] if row else 0

    def update_last_used(self, subscription_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE webpush_subscriptions SET last_used_at = ? WHERE id = ?",
                (clock.now().isoformat(), subscription_id),
            )
            conn.commit()

    def mark_expired(self, endpoint: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE webpush_subscriptions SET is_active = FALSE WHERE endpoint = ?",
                (endpoint,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_delivery_failure(self, endpoint: str) -> int:
        """配信失敗を記録し、更新後の連続失敗回数を返す。"""
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE webpush_subscriptions
                SET consecutive_failure_count = consecutive_failure_count + 1
                WHERE endpoint = ?
                """,
                (endpoint,),
            )
            row = conn.execute(
                "SELECT consecutive_failure_count FROM webpush_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
            conn.commit()
            return row["consecutive_failure_count"] if row else 0

    def record_delivery_success(self, endpoint: str) -> None:
        """配信成功時に連続失敗回数をリセットする。"""
        with self.connection() as conn:
            conn.execute(
                "UPDATE webpush_subscriptions SET consecutive_failure_count = 0 WHERE endpoint = ?",
                (endpoint,),
            )
            conn.commit()

    def delete_inactive_subscriptions(self) -> int:
        with self.connection() as conn:
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
        now = clock.now()
        with self.connection() as conn:
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
        with self.connection() as conn:
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

    def get_delivery_stats(self, days: int = 30) -> DeliveryStats:
        since = clock.now() - timedelta(days=days)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM webpush_delivery_logs
                WHERE sent_at >= ?
                GROUP BY status
                """,
                ((since - datetime.resolution).isoformat(),),
            ).fetchall()

        counts = {"sent": 0, "failed": 0, "expired": 0}
        total = 0
        for row in rows:
            count = row["count"]
            counts[row["status"]] = count
            total += count
        return DeliveryStats(total=total, **counts)

    def get_delivery_timeseries(self, days: int = 30) -> list[DeliveryDailyStats]:
        """配信結果の日次推移を返す (F3)。"""
        since = clock.now() - timedelta(days=days)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DATE(SUBSTR(sent_at, 1, 19)) as date, status, COUNT(*) as count
                FROM webpush_delivery_logs
                WHERE sent_at >= ?
                GROUP BY DATE(SUBSTR(sent_at, 1, 19)), status
                ORDER BY date
                """,
                (since.isoformat(),),
            ).fetchall()

        by_date: dict[str, dict[str, int]] = {}
        for row in rows:
            by_date.setdefault(row["date"], {})[row["status"]] = row["count"]
        return [
            DeliveryDailyStats(
                date=date,
                sent=counts.get("sent", 0),
                failed=counts.get("failed", 0),
                expired=counts.get("expired", 0),
            )
            for date, counts in by_date.items()
        ]

    def get_last_delivery_time(self) -> datetime | None:
        with self.connection() as conn:
            row = conn.execute("SELECT MAX(sent_at) as last_sent FROM webpush_delivery_logs").fetchone()
        if row is None or row["last_sent"] is None:
            return None
        return datetime.fromisoformat(row["last_sent"])

    def get_group_subscription_stats(self) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT {self._group_filter_column} FROM webpush_subscriptions WHERE is_active = TRUE"  # noqa: S608
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
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT product_filter FROM webpush_subscriptions
                WHERE is_active = TRUE AND product_filter IS NOT NULL
                """
            ).fetchall()

        product_counts: dict[str, int] = {}
        for row in rows:
            product_filter = row[CANONICAL_PRODUCT_FILTER_COLUMN]
            if not product_filter:
                continue
            for product_id in json.loads(product_filter):
                product_counts[product_id] = product_counts.get(product_id, 0) + 1
        return product_counts

    def _row_to_subscription(self, row: sqlite3.Row) -> WebPushSubscriptionRecord:
        group_filter = json.loads(row[self._group_filter_column]) if row[self._group_filter_column] else None
        event_type_filter = json.loads(row["event_type_filter"]) if row["event_type_filter"] else None
        product_filter = (
            json.loads(row[CANONICAL_PRODUCT_FILTER_COLUMN]) if row[CANONICAL_PRODUCT_FILTER_COLUMN] else None
        )
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
