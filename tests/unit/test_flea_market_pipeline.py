# ruff: noqa: S101
"""price_platform.store.flea_market_pipeline のユニットテスト."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from types import SimpleNamespace

import my_lib.store.flea_market
import selenium.common.exceptions

from price_platform.store.fetcher_common import FilterResult, ProductNameRule, ReferencePrices
from price_platform.store.flea_market_pipeline import FleaMarketPipelineMixin


@dataclass(frozen=True)
class FakePrice:
    price: int
    title: str = ""


@dataclass
class FakeSearchModule:
    results: list = field(default_factory=list)
    conditions: list = field(default_factory=list)

    def search(self, driver, wait, condition, max_items):
        self.conditions.append((condition, max_items))
        return self.results

    def warmup(self, driver, wait):
        return True


def _make_product(name="TEST-1"):
    return SimpleNamespace(name=name, id="prod-1", spec=SimpleNamespace(name=f"{name} SPEC"))


class FakeBase:
    """アプリ側 BaseFetcher の代役."""

    MAX_SEARCH_RESULTS = 20

    def __init__(self, config=None):
        self.config = config

    @contextlib.contextmanager
    def get_webdriver(self):
        yield ("driver", "wait")


class FakeFetcher(FleaMarketPipelineMixin, FakeBase):
    store_name_ja = "テストストア"
    store_name_en = "TestStore"
    absolute_minimum_price = 5000

    def __init__(self, *, search_module=None, reference_prices=None, fail_names=()):
        super().__init__(None, reference_prices=reference_prices)
        self._search_module = search_module or FakeSearchModule()
        self._fail_names = fail_names
        self.observed = []

    @property
    def search_module(self):
        return self._search_module

    def filter_by_name(self, prices, product, store_label):
        # タイトルに "NG" を含むものを落とす簡易フィルタ
        admitted = [p for p in prices if "NG" not in p.title]
        return FilterResult(rule=ProductNameRule(), admitted=admitted, decisions=[])

    def record_observations(self, product, store_label, reference_price, result):
        self.observed.append((product.name, store_label, reference_price, len(result.admitted)))

    def _fetch_prices(self, driver, wait, product):
        if product.name in self._fail_names:
            raise selenium.common.exceptions.WebDriverException("boom")
        return [FakePrice(price=10000)]

    def _fetch_sold_prices(self, driver, wait, product):
        return [FakePrice(price=20000)]


class TestApplyPriceFilters:
    def test_empty_returns_empty(self):
        fetcher = FakeFetcher()
        assert fetcher.apply_price_filters([], _make_product()) == []
        assert fetcher.observed == []  # 該当なしでは観測記録しない

    def test_name_filter_and_observation(self):
        fetcher = FakeFetcher()
        prices = [FakePrice(price=10000, title="OK"), FakePrice(price=11000, title="NG item")]
        result = fetcher.apply_price_filters(prices, _make_product())
        assert [p.title for p in result] == ["OK"]
        assert fetcher.observed == [("TEST-1", "テストストア", None, 1)]

    def test_absolute_minimum_price(self):
        fetcher = FakeFetcher()
        prices = [FakePrice(price=4999), FakePrice(price=5000)]
        result = fetcher.apply_price_filters(prices, _make_product())
        assert [p.price for p in result] == [5000]

    def test_suspicious_price_excluded_with_reference(self):
        reference = ReferencePrices(yodobashi={"TEST-1": 10000})
        fetcher = FakeFetcher(reference_prices=reference)
        # 0.6 未満 / 2.0 超を除外
        prices = [FakePrice(price=5900), FakePrice(price=8000), FakePrice(price=20001)]
        result = fetcher.apply_price_filters(prices, _make_product())
        assert [p.price for p in result] == [8000]

    def test_min_price_ratio_override(self):
        class DynamicFetcher(FakeFetcher):
            def min_price_ratio(self, product):
                return 0.3

        reference = ReferencePrices(yodobashi={"TEST-1": 10000})
        fetcher = DynamicFetcher(reference_prices=reference)
        prices = [FakePrice(price=5900)]  # 0.59 ≥ 0.3 なので通る
        result = fetcher.apply_price_filters(prices, _make_product())
        assert [p.price for p in result] == [5900]

    def test_sold_without_reference_warns_and_keeps(self, caplog):
        fetcher = FakeFetcher()
        prices = [FakePrice(price=9999999)]
        result = fetcher.apply_price_filters(prices, _make_product(), sold=True)
        assert len(result) == 1  # 基準価格なしでは価格フィルタをスキップ
        assert "基準価格なし" in caplog.text

    def test_sold_uses_sold_label(self):
        fetcher = FakeFetcher()
        fetcher.apply_price_filters([FakePrice(price=10000)], _make_product(), sold=True)
        assert fetcher.observed[0][1] == "テストストア(売却済)"


class TestSearchByName:
    def test_condition_for_fetch(self):
        module = FakeSearchModule()
        fetcher = FakeFetcher(search_module=module)
        fetcher.search_by_name("driver", "wait", _make_product())

        condition, max_items = module.conditions[0]
        assert condition.keyword == "TEST-1 SPEC"  # spec.name を使う
        assert condition.condition == [
            my_lib.store.flea_market.ItemCondition.NEW,
            my_lib.store.flea_market.ItemCondition.LIKE_NEW,
        ]
        assert condition.sale_status == my_lib.store.flea_market.SaleStatus.ON_SALE
        assert max_items == 20

    def test_condition_for_sold(self):
        module = FakeSearchModule()
        fetcher = FakeFetcher(search_module=module)
        fetcher.search_by_name("driver", "wait", _make_product(), sold=True)

        condition, _ = module.conditions[0]
        assert condition.sale_status == my_lib.store.flea_market.SaleStatus.SOLD_OUT


class TestScrapeTemplates:
    def test_scrape_uses_webdriver(self):
        fetcher = FakeFetcher()
        assert fetcher.scrape(_make_product())[0].price == 10000

    def test_scrape_all_handles_webdriver_exception(self):
        fetcher = FakeFetcher(fail_names=("BAD",))
        results = fetcher.scrape_all([_make_product("GOOD"), _make_product("BAD")])
        assert len(results["GOOD"]) == 1
        assert results["BAD"] == []

    def test_scrape_all_sold(self):
        fetcher = FakeFetcher()
        results = fetcher.scrape_all_sold([_make_product()])
        assert results["TEST-1"][0].price == 20000

    def test_warmup_delegates(self):
        fetcher = FakeFetcher()
        assert fetcher.warmup("driver", "wait") is True

    def test_set_reference_prices(self):
        fetcher = FakeFetcher()
        reference = ReferencePrices(yahoo={"X": 1})
        fetcher.set_reference_prices(reference)
        assert fetcher._reference_prices is reference
