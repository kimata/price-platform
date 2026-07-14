"""フリマ fetcher (Mercari / Rakuma / PayPay) の共通パイプライン。

各アプリの store/flea_market_base.py が fetch / sold で6重複させていた
「WebDriver セッション管理・名前検索・フィルタパイプライン
(名前一致 → 観測記録 → 絶対最低価格 → 疑わしい価格除外)」を提供する Mixin。

検索のオーケストレーション (model 検索の有無・実行順) はアプリごとに
意味のある差があるため吸い上げず、_fetch_prices / _fetch_sold_prices の
実装としてアプリ側に残す。アプリ側は検索結果から ScrapedPrice を構築し、
apply_price_filters() を呼ぶだけになる。
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

import my_lib.store.flea_market
import selenium.common.exceptions

from .fetcher_common import FilterResult, ReferencePrices, exclude_suspicious_prices

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support.wait import WebDriverWait

logger = logging.getLogger(__name__)

# 基準価格に対するしきい値の既定値 (60% 未満、200% 超を除外)
DEFAULT_SUSPICIOUS_PRICE_RATIO_MIN = 0.6
DEFAULT_SUSPICIOUS_PRICE_RATIO_MAX = 2.0


class _HasNameAndId(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def id(self) -> str: ...


class _HasPrice(Protocol):
    @property
    def price(self) -> int: ...


class FleaMarketSearchModule(Protocol):
    """フリマ検索モジュールの Protocol。"""

    def search(
        self,
        driver: WebDriver,
        wait: WebDriverWait,
        condition: my_lib.store.flea_market.SearchCondition,
        max_items: int,
    ) -> list[my_lib.store.flea_market.SearchResult]:
        """Search for items."""
        ...

    def warmup(
        self,
        driver: WebDriver,
        wait: WebDriverWait,
    ) -> bool:
        """Warm up the browser by visiting the site via Google search."""
        ...


class FleaMarketPipelineMixin[ProductT: _HasNameAndId, ScrapedPriceT: _HasPrice]:
    """フリマ fetcher の共通パイプライン Mixin。

    アプリ側の BaseFetcher (get_webdriver / config / MAX_SEARCH_RESULTS を提供)
    と多重継承して使う。サブクラスは以下を定義する:

    - store_name_ja / store_name_en / absolute_minimum_price
    - search_module プロパティ
    - filter_by_name() / record_observations() (アプリの base モジュールへの委譲)
    - _fetch_prices() / _fetch_sold_prices() (検索オーケストレーション)
    """

    store_name_ja: str
    store_name_en: str

    # 明らかに対象商品ではない価格を除外する下限
    absolute_minimum_price: int

    # 基準価格に対する上限比
    suspicious_price_ratio_max: float = DEFAULT_SUSPICIOUS_PRICE_RATIO_MAX

    # BaseFetcher 側が提供するメンバー (型チェック用の宣言)
    MAX_SEARCH_RESULTS: int
    config: Any

    if TYPE_CHECKING:

        def get_webdriver(self) -> AbstractContextManager[tuple[WebDriver, WebDriverWait]]: ...

    def __init__(self, *args: Any, reference_prices: ReferencePrices | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._reference_prices = reference_prices or ReferencePrices()

    @property
    @abstractmethod
    def search_module(self) -> FleaMarketSearchModule:
        """Return the search module for this flea market."""
        ...

    @abstractmethod
    def filter_by_name(
        self, prices: list[ScrapedPriceT], product: ProductT, store_label: str
    ) -> FilterResult[ScrapedPriceT]:
        """商品名一致フィルタ (アプリの base モジュールへ委譲する)。"""
        ...

    @abstractmethod
    def record_observations(
        self,
        product: ProductT,
        store_label: str,
        reference_price: int | None,
        result: FilterResult[ScrapedPriceT],
    ) -> None:
        """キーワード学習用の観測記録 (アプリの base モジュールへ委譲する)。"""
        ...

    @abstractmethod
    def _fetch_prices(
        self, driver: WebDriver, wait: WebDriverWait, product: ProductT
    ) -> list[ScrapedPriceT]:
        """検索オーケストレーション (アプリ固有)。"""
        ...

    @abstractmethod
    def _fetch_sold_prices(
        self, driver: WebDriver, wait: WebDriverWait, product: ProductT
    ) -> list[ScrapedPriceT]:
        """売却済みアイテムの検索オーケストレーション (アプリ固有)。"""
        ...

    def min_price_ratio(self, product: ProductT) -> float:  # noqa: ARG002
        """基準価格に対する下限比 (アプリ側で動的計算する場合はオーバーライド)。"""
        return DEFAULT_SUSPICIOUS_PRICE_RATIO_MIN

    def search_keyword(self, product: ProductT) -> str:
        """名前検索のキーワード (既定は product.spec.name)。"""
        return product.spec.name  # type: ignore[attr-defined]

    def set_reference_prices(self, reference_prices: ReferencePrices) -> None:
        """Set reference prices for filtering."""
        self._reference_prices = reference_prices

    def warmup(self, driver: WebDriver, wait: WebDriverWait) -> bool:
        """Google 検索経由でフリマサイトにアクセスしてウォームアップする。

        bot 検出を回避するため、初回アクセス前に呼び出す。
        """
        return self.search_module.warmup(driver, wait)

    def sold_label(self) -> str:
        return f"{self.store_name_ja}(売却済)"

    # --- scrape 系テンプレート ------------------------------------------------

    def scrape(self, product: ProductT) -> list[ScrapedPriceT]:
        """Fetch prices using WebDriver."""
        with self.get_webdriver() as (driver, wait):
            return self._fetch_prices(driver, wait, product)

    def scrape_with_webdriver(
        self,
        product: ProductT,
        driver: WebDriver,
        wait: WebDriverWait,
    ) -> list[ScrapedPriceT]:
        """Fetch prices using an external WebDriver."""
        return self._fetch_prices(driver, wait, product)

    def scrape_all(self, products: list[ProductT]) -> dict[str, list[ScrapedPriceT]]:
        """Fetch prices for multiple products using a single WebDriver session."""
        results: dict[str, list[ScrapedPriceT]] = {}
        with self.get_webdriver() as (driver, wait):
            for product in products:
                try:
                    prices = self._fetch_prices(driver, wait, product)
                    results[product.name] = prices
                    logger.info(f"{self.store_name_ja}: {product.name} - {len(prices)}件取得")
                except selenium.common.exceptions.WebDriverException as e:
                    logger.error(f"❌ {self.store_name_ja}: {product.name} - エラー: {e}")
                    results[product.name] = []
        return results

    def scrape_sold(self, product: ProductT) -> list[ScrapedPriceT]:
        """Fetch sold items."""
        with self.get_webdriver() as (driver, wait):
            return self._fetch_sold_prices(driver, wait, product)

    def scrape_sold_with_webdriver(
        self,
        product: ProductT,
        driver: WebDriver,
        wait: WebDriverWait,
    ) -> list[ScrapedPriceT]:
        """Fetch sold items using an external WebDriver."""
        return self._fetch_sold_prices(driver, wait, product)

    def scrape_all_sold(self, products: list[ProductT]) -> dict[str, list[ScrapedPriceT]]:
        """Fetch sold items for multiple products using a single WebDriver session."""
        results: dict[str, list[ScrapedPriceT]] = {}
        sold_label = self.sold_label()
        with self.get_webdriver() as (driver, wait):
            for product in products:
                try:
                    prices = self._fetch_sold_prices(driver, wait, product)
                    results[product.name] = prices
                except selenium.common.exceptions.WebDriverException as e:
                    logger.error(f"❌ {sold_label}: {product.name} - エラー: {e}")
                    results[product.name] = []
        return results

    # --- 検索・フィルタ部品 ---------------------------------------------------

    def search_by_name(
        self,
        driver: WebDriver,
        wait: WebDriverWait,
        product: ProductT,
        *,
        sold: bool = False,
    ) -> list[my_lib.store.flea_market.SearchResult]:
        """商品名 (search_keyword) で検索する。"""
        # NOTE: sale_status の既定は ON_SALE (None は「全て」の意味になるため使わない)
        condition = my_lib.store.flea_market.SearchCondition(
            keyword=self.search_keyword(product),
            condition=[
                my_lib.store.flea_market.ItemCondition.NEW,
                my_lib.store.flea_market.ItemCondition.LIKE_NEW,
            ],
            sale_status=(
                my_lib.store.flea_market.SaleStatus.SOLD_OUT
                if sold
                else my_lib.store.flea_market.SaleStatus.ON_SALE
            ),
        )

        return self.search_module.search(
            driver,
            wait,
            condition,
            max_items=self.MAX_SEARCH_RESULTS,
        )

    def apply_price_filters(
        self,
        prices: list[ScrapedPriceT],
        product: ProductT,
        *,
        sold: bool = False,
    ) -> list[ScrapedPriceT]:
        """共通フィルタパイプラインを適用する。

        名前一致フィルタ → 観測記録 → 絶対最低価格フィルタ →
        基準価格に対する疑わしい価格の除外、の順に適用する。
        """
        label = self.sold_label() if sold else self.store_name_ja

        if not prices:
            logger.info(f"{label}: {product.name} - 該当なし")
            return []

        if sold:
            logger.info(f"{label}: {product.name} - {len(prices)}件")
        else:
            cheapest = min(prices, key=lambda p: p.price)
            logger.info(f"{label}: {product.name} - {len(prices)}件、最安 ¥{cheapest.price:,}")

        # 商品名一致フィルタ (価格チェックより先)
        name_filter_result = self.filter_by_name(prices, product, label)

        reference_price = self._reference_prices.get_reference_price(product.name)
        self.record_observations(product, label, reference_price, name_filter_result)

        prices = name_filter_result.admitted

        # 絶対最低価格フィルタ (明らかに対象商品ではない価格を除外)
        before_count = len(prices)
        prices = [p for p in prices if p.price >= self.absolute_minimum_price]
        if len(prices) < before_count:
            logger.info(f"{label}: {product.name} - {before_count - len(prices)}件を最低価格フィルタで除外")

        # 基準価格に対する疑わしい価格の除外
        if sold and reference_price is None:
            logger.warning(
                f"⚠️ {label}: {product.name} - 基準価格なし、価格フィルタをスキップ "
                f"(yodobashi={product.name in self._reference_prices.yodobashi}, "
                f"yahoo={product.name in self._reference_prices.yahoo}, "
                f"amazon={product.name in self._reference_prices.amazon})"
            )
        if reference_price:
            label_en = f"{self.store_name_en}(sold)" if sold else self.store_name_en
            prices = exclude_suspicious_prices(
                prices,
                reference_price,
                self.min_price_ratio(product),
                self.suspicious_price_ratio_max,
                label_en,
                product.name,
            )

        return prices
