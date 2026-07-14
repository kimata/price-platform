"""価格データ永続化ストアの共通基底 (variant 次元つき fleama アプリ向け)。

pt-fleama (variant_id) と hp-fleama (color_id) の price_store が重複させていた、
「variant 列名のみが異なる」クエリ群を提供する。variant 列名はサブクラスの
VARIANT_COLUMN で与える。

移動対象は「VARIANT_COLUMN と _row_to_record / _variant_of フックだけで
表現できる」メソッドに限定する。統計・フリマ・売却済みなどアプリ固有モデルの
生成を伴うメソッドや、API シグネチャがアプリ間で異なるメソッド
(get_current_prices の include_unassigned/include_unknown 等) はアプリ側に残す。
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import my_lib.platform.time

from price_platform.sqlite_store import SQLiteStoreBase
from price_platform.store.selection import append_selection_filter

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class BasePriceStore(SQLiteStoreBase):
    """variant 次元を持つ価格ストアの共通基底。

    サブクラスは以下を定義する:
    - VARIANT_COLUMN: variant 列名 ("variant_id" / "color_id")
    - _row_to_record(row): 行を PriceRecord へ変換
    - _variant_of(record): PriceRecord から variant 値を取り出す
    - __init__ で self._local = threading.local() を設定し super().__init__(...) を呼ぶ

    注意: VARIANT_COLUMN はサブクラス定義のクラス定数であり、外部入力ではないため
    f-string での SQL 埋め込みは安全 (S608 は該当しない)。
    """

    VARIANT_COLUMN: ClassVar[str]

    _local: Any

    # --- サブクラスが提供するフック -----------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> Any:
        """DB 行を PriceRecord に変換する (アプリ固有)。"""
        raise NotImplementedError

    def _variant_of(self, record: Any) -> str | None:
        """PriceRecord から variant 値 (variant_id / color_id) を取り出す。"""
        raise NotImplementedError

    # --- 接続管理 -----------------------------------------------------------

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """リクエストスコープの共有接続があれば再利用し、なければ新規接続する。"""
        shared: sqlite3.Connection | None = getattr(self._local, "shared_conn", None)
        if shared is not None:
            yield shared
        else:
            with self.connection() as conn:
                conn.row_factory = sqlite3.Row
                yield conn

    @contextmanager
    def request_connection(self) -> Generator[None, None, None]:
        """リクエストライフサイクル中、1つの DB 接続を共有する。"""
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            self._local.shared_conn = conn
            try:
                yield
            finally:
                self._local.shared_conn = None

    # --- 現在価格の UPSERT --------------------------------------------------

    def _upsert_current_price(self, conn: sqlite3.Connection, record: Any) -> None:
        """current_prices テーブルを UPSERT する。"""
        vc = self.VARIANT_COLUMN
        conn.execute(
            f"""
            INSERT INTO current_prices
                (product_id, {vc}, store, is_used, price, url, title, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, {vc}, store, is_used) DO UPDATE SET
                price = excluded.price,
                url = excluded.url,
                title = excluded.title,
                updated_at = excluded.updated_at
            """,  # noqa: S608 - VARIANT_COLUMN はクラス定数
            (
                record.product_id,
                self._variant_of(record),
                record.store.value,
                record.is_used,
                record.price,
                record.url,
                record.title,
                record.recorded_at.isoformat(),
            ),
        )

    def _upsert_current_prices_batch(self, conn: sqlite3.Connection, records: list[Any]) -> None:
        """複数レコードで current_prices を UPSERT する。"""
        vc = self.VARIANT_COLUMN
        # SQLite の UNIQUE 制約は NULL を distinct 扱いするため、
        # variant=NULL のレコードは ON CONFLICT が発火しない。事前 DELETE で重複を防ぐ。
        null_variant_keys = [
            (r.product_id, r.store.value, r.is_used) for r in records if self._variant_of(r) is None
        ]
        if null_variant_keys:
            conn.executemany(
                f"DELETE FROM current_prices "
                f"WHERE product_id = ? AND {vc} IS NULL AND store = ? AND is_used = ?",  # noqa: S608
                null_variant_keys,
            )
        conn.executemany(
            f"""
            INSERT INTO current_prices
                (product_id, {vc}, store, is_used, price, url, title, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, {vc}, store, is_used) DO UPDATE SET
                price = excluded.price,
                url = excluded.url,
                title = excluded.title,
                updated_at = excluded.updated_at
            """,  # noqa: S608
            [
                (
                    r.product_id,
                    self._variant_of(r),
                    r.store.value,
                    r.is_used,
                    r.price,
                    r.url,
                    r.title,
                    r.recorded_at.isoformat(),
                )
                for r in records
            ],
        )

    # --- 価格の保存 ---------------------------------------------------------

    def save_price(self, record: Any) -> None:
        """単一の価格レコードを保存する。"""
        vc = self.VARIANT_COLUMN
        with self._get_connection() as conn:
            conn.execute(
                f"""
                INSERT INTO prices
                    (product_id, {vc}, store, price, url, title, is_used, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: S608
                (
                    record.product_id,
                    self._variant_of(record),
                    record.store.value,
                    record.price,
                    record.url,
                    record.title,
                    record.is_used,
                    record.recorded_at.isoformat(),
                ),
            )
            self._upsert_current_price(conn, record)
            conn.commit()

    def save_prices(self, records: list[Any]) -> None:
        """複数の価格レコードを保存する。"""
        if not records:
            return

        vc = self.VARIANT_COLUMN
        with self._get_connection() as conn:
            conn.executemany(
                f"""
                INSERT INTO prices
                    (product_id, {vc}, store, price, url, title, is_used, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: S608
                [
                    (
                        r.product_id,
                        self._variant_of(r),
                        r.store.value,
                        r.price,
                        r.url,
                        r.title,
                        r.is_used,
                        r.recorded_at.isoformat(),
                    )
                    for r in records
                ],
            )
            self._upsert_current_prices_batch(conn, records)
            conn.commit()
        logger.info(f"Saved {len(records)} price records")

    # --- 価格の取得 ---------------------------------------------------------

    def get_price_history(
        self,
        product_id: str,
        days: int = 30,
        store: Any = None,
        selection_key: Any = None,
    ) -> list[Any]:
        """製品の価格履歴を取得する。"""
        since = my_lib.platform.time.now() - timedelta(days=days)
        resolved_selection = str(selection_key) if selection_key is not None else None
        with self._get_connection() as conn:
            query = """
                SELECT * FROM prices
                WHERE product_id = ? AND recorded_at >= ?
            """
            params: list[object] = [product_id, since.isoformat()]

            if store:
                query += " AND store = ?"
                params.append(store.value)

            query, params = append_selection_filter(
                query=query,
                params=params,
                column_name=self.VARIANT_COLUMN,
                selection_value=resolved_selection,
            )

            query += " ORDER BY recorded_at ASC"
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_lowest_price(
        self,
        product_id: str,
        is_used: bool | None = None,
        days: int | None = None,
        selection_key: Any = None,
    ) -> Any:
        """製品の最安値レコードを取得する。"""
        since = None
        if days:
            since = my_lib.platform.time.now() - timedelta(days=days)
        resolved_selection = str(selection_key) if selection_key is not None else None

        with self._get_connection() as conn:
            query = "SELECT * FROM prices WHERE product_id = ?"
            params: list[object] = [product_id]

            if is_used is not None:
                query += " AND is_used = ?"
                params.append(is_used)

            if since:
                query += " AND recorded_at >= ?"
                params.append(since.isoformat())

            query, params = append_selection_filter(
                query=query,
                params=params,
                column_name=self.VARIANT_COLUMN,
                selection_value=resolved_selection,
            )

            query += " ORDER BY price ASC LIMIT 1"
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_lowest_price_by_stores(
        self,
        product_id: str,
        stores: list[Any],
        is_used: bool = False,
    ) -> int | None:
        """指定ストア群からの最安値を取得する。"""
        if not stores:
            return None

        with self._get_connection() as conn:
            placeholders = ",".join("?" for _ in stores)
            cursor = conn.execute(
                f"""
                SELECT MIN(price) as min_price
                FROM current_prices
                WHERE product_id = ?
                  AND store IN ({placeholders})
                  AND is_used = ?
                """,  # noqa: S608 - placeholders はストア数ぶんの ? のみ
                [product_id, *[s.value for s in stores], is_used],
            )
            row = cursor.fetchone()
            if row and row["min_price"] is not None:
                return row["min_price"]
            return None

    def get_current_prices_batch(self, product_ids: list[str]) -> dict[str, list[Any]]:
        """複数製品の現在価格を一括取得する。"""
        if not product_ids:
            return {}

        vc = self.VARIANT_COLUMN
        result: dict[str, list[Any]] = {pid: [] for pid in product_ids}
        with self._get_connection() as conn:
            placeholders = ",".join("?" for _ in product_ids)
            cursor = conn.execute(
                f"""
                SELECT product_id, {vc}, store, is_used, price, url, title, updated_at as recorded_at
                FROM current_prices
                WHERE product_id IN ({placeholders})
                """,  # noqa: S608
                product_ids,
            )
            for row in cursor.fetchall():
                record = self._row_to_record(row)
                result[record.product_id].append(record)
        return result

    # --- 更新時刻 -----------------------------------------------------------

    def get_last_update_time(self) -> datetime | None:
        """DB 中で最も新しい recorded_at を取得する。"""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT MAX(recorded_at) as last_update FROM prices")
            row = cursor.fetchone()
            if row and row["last_update"]:
                return datetime.fromisoformat(row["last_update"])
            return None

    def get_product_last_updates(self) -> dict[str, datetime]:
        """製品ごとの最新更新時刻を取得する。"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT product_id, MAX(recorded_at) as last_update FROM prices GROUP BY product_id"
            )
            result: dict[str, datetime] = {}
            for row in cursor:
                if row["last_update"]:
                    result[row["product_id"]] = datetime.fromisoformat(row["last_update"])
            return result

    # --- クリーンアップ -----------------------------------------------------

    def cleanup_old_records(self, days: int = 365) -> int:
        """指定日数より古いレコードを削除する。"""
        cutoff = my_lib.platform.time.now() - timedelta(days=days)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM prices WHERE recorded_at < ?",
                (cutoff.isoformat(),),
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted_count} old price records")
            return deleted_count
