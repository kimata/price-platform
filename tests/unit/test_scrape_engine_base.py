"""price_platform.store.scrape_engine_base のユニットテスト."""

from __future__ import annotations

import contextlib
import enum
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from price_platform.store.scrape_engine_base import BaseScrapeEngine, ScrapeResult


class Store(enum.Enum):
    AMAZON = "amazon"
    YODOBASHI = "yodobashi"
    YAHOO = "yahoo"
    MERCARI = "mercari"


@dataclass(frozen=True)
class FakePrice:
    price: int


class FakePool:
    def __init__(self):
        self.closed = False
        self.timeouts: list[Any] = []
        self.successes: list[Any] = []

    def get(self, maker):
        return (f"driver-{maker}", f"wait-{maker}")

    def notify_timeout(self, maker):
        self.timeouts.append(maker)

    def notify_success(self, maker):
        self.successes.append(maker)

    def close_all(self):
        self.closed = True


class FakeFetcher:
    def __init__(self, *, prices=None, per_item=None):
        self._prices = prices or []
        self._per_item = per_item or {}
        self.scraped: list[Any] = []

    def scrape(self, item):
        self.scraped.append(item)
        return self._per_item.get(item.name, self._prices)

    def scrape_with_webdriver(self, item, driver, wait):
        self.scraped.append(item)
        return self._per_item.get(item.name, self._prices)

    def scrape_sold_with_webdriver(self, item, driver, wait):
        self.scraped.append(item)
        return self._per_item.get(item.name, self._prices)

    def scrape_all(self, items):
        return {item.name: self._per_item.get(item.name, self._prices) for item in items}


def _make_item(name="I1", maker="M1"):
    return SimpleNamespace(id=f"id-{name}", name=name, maker=maker)


class SampleEngine(BaseScrapeEngine):
    WEBDRIVER_STORES = {Store.MERCARI}
    TRUSTED_STORES = [Store.YODOBASHI, Store.YAHOO]
    FILTERED_STORES = {Store.MERCARI}
    FLEA_MARKET_STORES = {Store.MERCARI}
    REFERENCE_PRICE_STORES = [Store.YODOBASHI, Store.YAHOO]

    def __init__(self, **kwargs):
        self.pool = FakePool()
        self.scraped_items: list[Any] = []
        # 既定でスリープを無効化 (テスト高速化)
        kwargs.setdefault("ci_mode", True)
        super().__init__(**kwargs)

    @property
    def amazon_store(self):
        return Store.AMAZON

    @property
    def dummy_store(self):
        return Store.YODOBASHI

    def _make_pool(self):
        return self.pool

    def _make_result(self, **kwargs):
        return ScrapeResult(**kwargs)

    def _is_item_applicable(self, item, store_type):
        return True

    def _scrape_item(self, item, target_stores, pool, amazon_prices=None, warmed_up_makers=None):
        # 単純な per-item 実装: 各対象ストアで1回リトライ付きスクレイプ
        self.scraped_items.append(item.name)
        results = []
        for store_type in sorted(target_stores, key=lambda s: s.value):
            fetcher = self._fetchers.get(store_type)
            if fetcher is None:
                continue
            results.append(self._scrape_with_retry(item, store_type, fetcher, pool))
        return results


class TestScrapeAll:
    def test_amazon_only_marks_last(self):
        engine = SampleEngine(config=None)
        engine.set_fetchers({Store.AMAZON: FakeFetcher(prices=[FakePrice(1000)])})
        results = engine.scrape_all([_make_item("A"), _make_item("B")])
        assert len(results) == 2
        assert all(r.store == Store.AMAZON for r in results)
        assert all(r.is_last_store_for_product for r in results)

    def test_amazon_batch_and_per_item(self):
        engine = SampleEngine(config=None)
        engine.set_fetchers(
            {
                Store.AMAZON: FakeFetcher(per_item={"A": [FakePrice(999)]}),
                Store.YODOBASHI: FakeFetcher(prices=[FakePrice(2000)]),
            }
        )
        results = engine.scrape_all([_make_item("A")])
        stores = [r.store for r in results]
        assert Store.AMAZON in stores
        assert Store.YODOBASHI in stores
        # 最後のストア結果が is_last_store_for_product
        assert results[-1].is_last_store_for_product

    def test_empty_stores_yields_dummy_result(self):
        engine = SampleEngine(config=None)
        # フェッチャーは Amazon 以外を1つ登録するが _scrape_item が空を返すよう細工

        class EmptyEngine(SampleEngine):
            def _scrape_item(self, item, target_stores, pool, amazon_prices=None, warmed_up_makers=None):
                return []

        e2 = EmptyEngine(config=None)
        e2.set_fetchers({Store.YODOBASHI: FakeFetcher()})
        results = e2.scrape_all([_make_item("A")])
        assert len(results) == 1
        assert results[0].store == Store.YODOBASHI
        assert results[0].is_last_store_for_product
        assert results[0].prices == []

    def test_shutdown_check_aborts(self):
        engine = SampleEngine(config=None)
        engine.set_fetchers({Store.YODOBASHI: FakeFetcher(prices=[FakePrice(1)])})
        results = engine.scrape_all([_make_item("A")], shutdown_check=lambda: True)
        assert results == []


class TestRetry:
    def test_webdriver_store_uses_pool(self):
        engine = SampleEngine(config=None)
        fetcher = FakeFetcher(prices=[FakePrice(500)])
        with engine.webdriver_context() as pool:
            result = engine._scrape_with_retry(_make_item("A", maker="MK"), Store.MERCARI, fetcher, pool)
        assert result.success
        assert result.prices == [FakePrice(500)]
        assert engine.pool.successes == ["MK"]

    def test_sold_retry_marks_sold(self):
        engine = SampleEngine(config=None)
        fetcher = FakeFetcher(prices=[FakePrice(300)])
        result = engine._scrape_sold_with_retry(_make_item("A", maker="MK"), Store.MERCARI, fetcher, engine.pool)
        assert result.is_sold
        assert result.prices == [FakePrice(300)]


class TestHooks:
    def test_shuffle_hook_used(self):
        order: list[str] = []

        class ShuffleEngine(SampleEngine):
            def _shuffle_items(self, items):
                return list(reversed(items))

            def _scrape_item(self, item, target_stores, pool, amazon_prices=None, warmed_up_makers=None):
                order.append(item.name)
                return []

        engine = ShuffleEngine(config=None)
        engine.set_fetchers({Store.YODOBASHI: FakeFetcher()})
        list(engine.scrape_iter_with_pool([_make_item("A"), _make_item("B")], None, shuffle=True))
        assert order == ["B", "A"]

    def test_metrics_item_key_default_is_name(self):
        recorded: list[tuple[str, str]] = []
        mm = SimpleNamespace(
            start_item=lambda store, key: recorded.append((store, key)) or SimpleNamespace(
                success=lambda: None, failure=lambda msg=None: None
            )
        )
        engine = SampleEngine(config=None, metrics_manager=mm)
        engine._scrape_with_retry(_make_item("A"), Store.YODOBASHI, FakeFetcher(prices=[]), None)
        assert recorded == [("yodobashi", "A")]

    def test_price_threshold_default_empty(self):
        engine = SampleEngine(config=None)
        assert engine._price_threshold == {}

    def test_historical_reference_price(self):
        store = SimpleNamespace(
            get_lowest_price_by_stores=lambda name, stores: 4200 if name == "A" else None
        )
        engine = SampleEngine(config=None, price_store=store)
        assert engine._get_historical_reference_price("A") == 4200
        assert engine._get_historical_reference_price("Z") is None


class TestWarmup:
    def test_warmup_calls_flea_fetchers(self):
        from price_platform.store.flea_market_pipeline import FleaMarketPipelineMixin

        warmed: list[Any] = []

        class FleaFetcher(FleaMarketPipelineMixin):
            store_name_ja = "テスト"
            store_name_en = "Test"
            absolute_minimum_price = 100

            @property
            def search_module(self):
                return None

            def filter_by_name(self, prices, product, store_label):  # pragma: no cover
                return None

            def record_observations(self, product, store_label, reference_price, result):  # pragma: no cover
                return None

            def _fetch_prices(self, driver, wait, product):  # pragma: no cover
                return []

            def _fetch_sold_prices(self, driver, wait, product):  # pragma: no cover
                return []

            def warmup(self, driver, wait):
                warmed.append((driver, wait))
                return True

        engine = SampleEngine(config=None)
        engine.set_fetchers({Store.MERCARI: FleaFetcher()})
        maker = SimpleNamespace(value="MK")
        with contextlib.suppress(Exception):
            engine._warmup_flea_markets(maker, engine.pool)
        assert len(warmed) == 1
