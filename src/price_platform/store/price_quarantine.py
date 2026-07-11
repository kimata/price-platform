"""異常価格の検疫ストア (F4)。

0 円や桁違い価格のスクレイプ不良は、ゼロ除算だけでなく誤った
「史上最安値」イベントの投稿というサイトの信頼性事故につながる。
除外した事実を理由付きで記録し、除外率をメトリクス化することで、
ストア側の HTML 構造変化によるスクレイパー劣化を早期検知できるようにする。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from price_platform.platform import clock
from price_platform.schema_registry import resolve_schema_path
from price_platform.sqlite_store import SQLiteStoreBase

QuarantineReason = Literal["below_min_threshold", "above_max_threshold"]


@dataclass(frozen=True)
class QuarantinedPrice:
    """検疫対象として除外された 1 件の価格観測。"""

    product_name: str
    store_name: str
    price: int
    reason: str
    reference_price: int | None = None
    title: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class QuarantineStats:
    """ストア × 理由ごとの検疫件数。"""

    store_name: str
    reason: str
    count: int


class PriceQuarantineStore(SQLiteStoreBase):
    """SQLite-backed quarantine log for suspicious price observations."""

    def __init__(self, db_path: pathlib.Path):
        super().__init__(
            db_path=db_path,
            schema_path=resolve_schema_path("sqlite_price_quarantine.schema"),
        )

    def record(self, entry: QuarantinedPrice) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO price_quarantine
                    (product_name, store_name, price, reference_price, reason, title, url, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.product_name,
                    entry.store_name,
                    entry.price,
                    entry.reference_price,
                    entry.reason,
                    entry.title,
                    entry.url,
                    clock.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_stats(self, days: int = 30) -> list[QuarantineStats]:
        """ストア × 理由ごとの検疫件数を返す (除外率メトリクス用)。"""
        since = clock.now() - timedelta(days=days)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT store_name, reason, COUNT(*) as count
                FROM price_quarantine
                WHERE recorded_at >= ?
                GROUP BY store_name, reason
                ORDER BY count DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        return [
            QuarantineStats(store_name=row["store_name"], reason=row["reason"], count=row["count"])
            for row in rows
        ]

    def cleanup_old(self, days: int = 90) -> int:
        cutoff = clock.now() - timedelta(days=days)
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM price_quarantine WHERE recorded_at < ?", (cutoff.isoformat(),)
            )
            conn.commit()
            return cursor.rowcount
