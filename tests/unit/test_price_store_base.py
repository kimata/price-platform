"""price_platform.store.price_store_base のユニットテスト.

variant 列名を "vc_id" として具象化し、共通クエリ群の挙動を検証する。
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

import my_lib.time
import pytest

from price_platform.store.price_store_base import BasePriceStore


class Store(enum.Enum):
    A = "a"
    B = "b"


@dataclass
class Rec:
    product_id: str
    vc_id: str | None
    store: Store
    price: int
    recorded_at: datetime
    is_used: bool = False
    url: str | None = None
    title: str | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    vc_id TEXT,
    store TEXT NOT NULL,
    price INTEGER NOT NULL,
    url TEXT,
    title TEXT,
    is_used INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS current_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    vc_id TEXT,
    store TEXT NOT NULL,
    is_used INTEGER NOT NULL DEFAULT 0,
    price INTEGER NOT NULL,
    url TEXT,
    title TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, vc_id, store, is_used)
);
"""


class SampleStore(BasePriceStore):
    VARIANT_COLUMN = "vc_id"

    def __init__(self, db_path, schema_path):
        self._local = threading.local()
        super().__init__(db_path=db_path, schema_path=schema_path)

    def _row_to_record(self, row):
        return Rec(
            product_id=row["product_id"],
            vc_id=row["vc_id"] if "vc_id" in row.keys() else None,  # noqa: SIM118 - sqlite3.Row は in が値検索
            store=Store(row["store"]),
            price=row["price"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            is_used=bool(row["is_used"]),
            url=row["url"] if "url" in row.keys() else None,  # noqa: SIM118 - sqlite3.Row は in が値検索
            title=row["title"] if "title" in row.keys() else None,  # noqa: SIM118 - sqlite3.Row は in が値検索
        )

    def _variant_of(self, record):
        return record.vc_id


@pytest.fixture
def store(tmp_path):
    schema = tmp_path / "price.schema"
    schema.write_text(SCHEMA)
    return SampleStore(db_path=tmp_path / "data" / "price.db", schema_path=schema)


def _rec(pid="p1", vc: str | None = "V1", store=Store.A, price=1000, days_ago=0, is_used=False):
    return Rec(
        product_id=pid,
        vc_id=vc,
        store=store,
        price=price,
        recorded_at=my_lib.time.now() - timedelta(days=days_ago),
        is_used=is_used,
    )


class TestSaveAndGet:
    def test_save_price_and_current_batch(self, store):
        store.save_price(_rec(price=1000))
        batch = store.get_current_prices_batch(["p1"])
        assert len(batch["p1"]) == 1
        assert batch["p1"][0].price == 1000
        assert batch["p1"][0].vc_id == "V1"

    def test_upsert_replaces_current(self, store):
        store.save_price(_rec(price=1000))
        store.save_price(_rec(price=900))  # 同一 (product, vc, store, is_used)
        batch = store.get_current_prices_batch(["p1"])
        assert len(batch["p1"]) == 1
        assert batch["p1"][0].price == 900

    def test_null_variant_no_duplicate(self, store):
        store.save_prices([_rec(vc=None, price=1000)])
        store.save_prices([_rec(vc=None, price=800)])
        batch = store.get_current_prices_batch(["p1"])
        assert len(batch["p1"]) == 1
        assert batch["p1"][0].price == 800

    def test_save_prices_empty(self, store):
        store.save_prices([])  # 例外なし
        assert store.get_current_prices_batch(["p1"]) == {"p1": []}


class TestHistoryAndLowest:
    def _seed(self, store):
        store.save_prices(
            [
                _rec(price=1200, days_ago=20),
                _rec(price=1100, days_ago=10),
                _rec(price=1000, days_ago=1),
                _rec(vc="V2", store=Store.B, price=1500, days_ago=1),
            ]
        )

    def test_history_ordered(self, store):
        self._seed(store)
        hist = store.get_price_history("p1", days=90)
        assert [h.price for h in hist] == [1200, 1100, 1000, 1500]

    def test_history_store_filter(self, store):
        self._seed(store)
        hist = store.get_price_history("p1", days=90, store=Store.B)
        assert [h.price for h in hist] == [1500]

    def test_history_selection_filter(self, store):
        self._seed(store)
        hist = store.get_price_history("p1", days=90, selection_key="V2")
        assert [h.price for h in hist] == [1500]

    def test_lowest_price(self, store):
        self._seed(store)
        low = store.get_lowest_price("p1", days=90)
        assert low is not None
        assert low.price == 1000

    def test_lowest_price_by_stores(self, store):
        self._seed(store)
        assert store.get_lowest_price_by_stores("p1", [Store.A, Store.B]) == 1000
        assert store.get_lowest_price_by_stores("p1", [Store.B]) == 1500
        assert store.get_lowest_price_by_stores("nope", [Store.A]) is None
        assert store.get_lowest_price_by_stores("p1", []) is None


class TestMisc:
    def test_last_update_times(self, store):
        assert store.get_last_update_time() is None
        store.save_prices([_rec(pid="p1", days_ago=1), _rec(pid="p2", days_ago=0)])
        assert store.get_last_update_time() is not None
        updates = store.get_product_last_updates()
        assert set(updates.keys()) == {"p1", "p2"}

    def test_cleanup_old_records(self, store):
        store.save_prices([_rec(days_ago=400), _rec(days_ago=1)])
        deleted = store.cleanup_old_records(days=365)
        assert deleted == 1
        assert store.get_last_update_time() is not None

    def test_request_connection_shares(self, store):
        with store.request_connection():
            store.save_price(_rec(price=1000))
            batch = store.get_current_prices_batch(["p1"])
        assert batch["p1"][0].price == 1000
