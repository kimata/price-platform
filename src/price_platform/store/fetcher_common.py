"""商品別取得クラスで共有する基底機能。"""

from __future__ import annotations

import contextlib
import logging
import pathlib
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Generic, Protocol, TypeVar

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from collections.abc import Generator

    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support.wait import WebDriverWait

logger = logging.getLogger(__name__)

class _HasName(Protocol):
    @property
    def name(self) -> str: ...


class _HasPrice(Protocol):
    @property
    def price(self) -> int: ...


ProductT = TypeVar("ProductT", bound=_HasName)
ScrapedPriceT = TypeVar("ScrapedPriceT", bound=_HasPrice)
StoreT = TypeVar("StoreT")


class _SeleniumConfigLike(Protocol):
    @property
    def data_path(self) -> pathlib.Path: ...
    @property
    def headless(self) -> bool: ...


class FetcherConfigProtocol(Protocol):
    """`SharedBaseFetcher` が必要とする最小限の設定インターフェース。"""

    @property
    def selenium(self) -> _SeleniumConfigLike: ...


ConfigT = TypeVar("ConfigT", bound=FetcherConfigProtocol)


@dataclass(frozen=True)
class ProductNameRule:
    required_keywords: tuple[str, ...] = ()
    anchor_keywords: tuple[str, ...] = ()
    flea_market_ng_words: tuple[str, ...] = ()
    condition_ng_words: tuple[str, ...] = ()
    partial_item_ng_words: tuple[str, ...] = ()
    parts_ng_words: tuple[str, ...] = ()
    parts_ng_price_threshold: int | None = None
    exclude_product_names: tuple[str, ...] = ()
    exclude_yo_titles: bool = False
    exclude_empty_box_titles: bool = False


@dataclass(frozen=True)
class ColorLabelFilterConfig:
    color_family_keywords: dict[str, tuple[str, ...]]


class FilterReason(StrEnum):
    EXCLUDE_PRODUCT_NAME = "exclude_product_name"
    MISSING_KEYWORDS = "missing_keywords"
    FLEA_MARKET_NG_WORD = "flea_market_ng_word"
    CONDITION_NG_WORD = "condition_ng_word"
    PARTIAL_ITEM_NG_WORD = "partial_item_ng_word"
    PARTS_NG_WORD_BELOW_THRESHOLD = "parts_ng_word_below_threshold"
    POLICY_EXCLUDED = "policy_excluded"


@dataclass(frozen=True)
class TitleExclusion:
    reason: FilterReason
    matched_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilterDecision(Generic[ScrapedPriceT]):
    listing: ScrapedPriceT
    admitted: bool
    reason: FilterReason | None = None
    missing_keywords: tuple[str, ...] = ()
    matched_ng_words: tuple[str, ...] = ()
    matched_partial_item_words: tuple[str, ...] = ()
    matched_parts_words: tuple[str, ...] = ()
    matched_exclude_product_name: str | None = None


@dataclass(frozen=True)
class FilterResult(Generic[ScrapedPriceT]):
    rule: ProductNameRule
    admitted: list[ScrapedPriceT]
    decisions: list[FilterDecision[ScrapedPriceT]]

    def __iter__(self):
        return iter(self.admitted)

    def __len__(self) -> int:
        return len(self.admitted)

    def __getitem__(self, index):
        return self.admitted[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.admitted == other
        return super().__eq__(other)


class ProductNameMatchingPolicy(Protocol):
    """製品名一致判定の差し替えポリシー。"""

    def build_rule(self, *, product_name: str, base_rule: ProductNameRule) -> ProductNameRule: ...

    def keyword_in_title(self, keyword: str, title_upper: str) -> bool: ...

    def normalize_title(self, title: str) -> str: ...

    def get_title_exclusion(
        self,
        *,
        title: str,
        title_upper: str,
        title_normalized: str,
        rule: ProductNameRule,
    ) -> TitleExclusion | None: ...


@dataclass(frozen=True)
class FetcherProfile:
    """取得処理の共通プロファイル。"""

    product_name_rule: ProductNameRule
    color_label_filter: ColorLabelFilterConfig
    webdriver_profile_name: str
    matching_policy: ProductNameMatchingPolicy


@dataclass
class ReferencePrices:
    """参照価格を優先順位つきで保持するコンテナ。"""

    yodobashi: dict[str, int] = field(default_factory=dict)
    yahoo: dict[str, int] = field(default_factory=dict)
    amazon: dict[str, int] = field(default_factory=dict)

    def get_reference_price(self, product_name: str) -> int | None:
        if product_name in self.yodobashi:
            return self.yodobashi[product_name]
        if product_name in self.yahoo:
            return self.yahoo[product_name]
        if product_name in self.amazon:
            return self.amazon[product_name]
        return None


class DefaultProductNameMatchingPolicy:
    """標準的な製品名一致判定ポリシー。"""

    def build_rule(self, *, product_name: str, base_rule: ProductNameRule) -> ProductNameRule:
        required_keywords = base_rule.required_keywords or tuple(product_name.split())
        return ProductNameRule(
            required_keywords=tuple(required_keywords),
            anchor_keywords=tuple(base_rule.anchor_keywords),
            flea_market_ng_words=tuple(base_rule.flea_market_ng_words),
            condition_ng_words=tuple(base_rule.condition_ng_words),
            partial_item_ng_words=tuple(base_rule.partial_item_ng_words),
            parts_ng_words=tuple(base_rule.parts_ng_words),
            parts_ng_price_threshold=base_rule.parts_ng_price_threshold,
            exclude_product_names=tuple(base_rule.exclude_product_names),
            exclude_yo_titles=base_rule.exclude_yo_titles,
            exclude_empty_box_titles=base_rule.exclude_empty_box_titles,
        )

    def keyword_in_title(self, keyword: str, title_upper: str) -> bool:
        return _keyword_in_title(keyword, title_upper)

    def normalize_title(self, title: str) -> str:
        return unicodedata.normalize("NFKC", title).upper()

    def get_title_exclusion(
        self,
        *,
        title: str,
        title_upper: str,
        title_normalized: str,
        rule: ProductNameRule,
    ) -> TitleExclusion | None:
        _ = title_upper
        if rule.exclude_yo_titles and "用" in title and "専用" not in title:
            return TitleExclusion(reason=FilterReason.POLICY_EXCLUDED)
        if rule.exclude_empty_box_titles and "空箱" in title:
            return TitleExclusion(reason=FilterReason.POLICY_EXCLUDED)

        matched_flea_market = tuple(ng for ng in rule.flea_market_ng_words if ng in title_normalized)
        if matched_flea_market:
            return TitleExclusion(
                reason=FilterReason.FLEA_MARKET_NG_WORD,
                matched_words=matched_flea_market,
            )

        matched_condition = tuple(ng for ng in rule.condition_ng_words if ng in title)
        if matched_condition:
            return TitleExclusion(
                reason=FilterReason.CONDITION_NG_WORD,
                matched_words=matched_condition,
            )

        matched_partial = tuple(ng for ng in rule.partial_item_ng_words if ng in title)
        if matched_partial:
            return TitleExclusion(
                reason=FilterReason.PARTIAL_ITEM_NG_WORD,
                matched_words=matched_partial,
            )

        return None


DEFAULT_PRODUCT_NAME_MATCHING_POLICY = DefaultProductNameMatchingPolicy()


def _keyword_in_title(keyword: str, title_upper: str) -> bool:
    kw_upper = keyword.upper()
    pattern = re.escape(kw_upper)
    if re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", title_upper):
        return True

    kw_no_hyphen = kw_upper.replace("-", "")
    title_no_hyphen = title_upper.replace("-", "")
    if kw_no_hyphen != kw_upper or title_no_hyphen != title_upper:
        pattern_no_hyphen = re.escape(kw_no_hyphen)
        if re.search(rf"(?<![A-Z0-9]){pattern_no_hyphen}(?![A-Z0-9])", title_no_hyphen):
            return True

    return False


def default_keyword_in_title(keyword: str, title_upper: str) -> bool:
    return _keyword_in_title(keyword, title_upper)


def filter_by_product_name_match(
    prices: list[ScrapedPriceT],
    product_name: str,
    store_name: str,
    *,
    rule: ProductNameRule,
    matching_policy: ProductNameMatchingPolicy = DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
) -> FilterResult[ScrapedPriceT]:
    """対象製品名に合わない出品を除外する。"""
    decisions: list[FilterDecision[ScrapedPriceT]] = []
    if not rule.required_keywords:
        return FilterResult(
            rule=rule,
            admitted=list(prices),
            decisions=[FilterDecision(listing=price, admitted=True) for price in prices],
        )

    filtered: list[ScrapedPriceT] = []
    exclude_name_keywords = {
        exclude_name: matching_policy.build_rule(
            product_name=exclude_name,
            base_rule=ProductNameRule(
                flea_market_ng_words=(),
                condition_ng_words=(),
            ),
        ).required_keywords
        for exclude_name in rule.exclude_product_names
    }

    for price in prices:
        title = getattr(price, "title", "") or ""
        title_normalized = matching_policy.normalize_title(title)
        title_upper = title_normalized

        matched_exclude = None
        for exclude_name, exclude_keywords in exclude_name_keywords.items():
            if all(matching_policy.keyword_in_title(kw, title_upper) for kw in exclude_keywords):
                matched_exclude = exclude_name
                break

        if matched_exclude:
            logger.debug(
                "%s: %s - 別製品「%s」にマッチするため除外 「%s」",
                store_name,
                product_name,
                matched_exclude,
                f"{title[:50]}..." if len(title) > 50 else title,
            )
            decisions.append(
                FilterDecision(
                    listing=price,
                    admitted=False,
                    reason=FilterReason.EXCLUDE_PRODUCT_NAME,
                    matched_exclude_product_name=matched_exclude,
                )
            )
            continue

        missing_keywords = [
            kw for kw in rule.required_keywords if not matching_policy.keyword_in_title(kw, title_upper)
        ]
        if missing_keywords:
            logger.debug(
                "%s: %s - タイトル不一致で除外 「%s」（不足: %s）",
                store_name,
                product_name,
                f"{title[:50]}..." if len(title) > 50 else title,
                ", ".join(missing_keywords),
            )
            decisions.append(
                FilterDecision(
                    listing=price,
                    admitted=False,
                    reason=FilterReason.MISSING_KEYWORDS,
                    missing_keywords=tuple(missing_keywords),
                )
            )
            continue

        title_exclusion = matching_policy.get_title_exclusion(
            title=title,
            title_upper=title_upper,
            title_normalized=title_normalized,
            rule=rule,
        )
        if title_exclusion is not None:
            decision = FilterDecision(
                listing=price,
                admitted=False,
                reason=title_exclusion.reason,
            )
            if title_exclusion.reason in (FilterReason.FLEA_MARKET_NG_WORD, FilterReason.CONDITION_NG_WORD):
                decision = FilterDecision(
                    listing=price,
                    admitted=False,
                    reason=title_exclusion.reason,
                    matched_ng_words=title_exclusion.matched_words,
                )
            elif title_exclusion.reason is FilterReason.PARTIAL_ITEM_NG_WORD:
                decision = FilterDecision(
                    listing=price,
                    admitted=False,
                    reason=title_exclusion.reason,
                    matched_partial_item_words=title_exclusion.matched_words,
                )
            decisions.append(decision)
            continue

        if (
            rule.parts_ng_words
            and rule.parts_ng_price_threshold is not None
            and price.price < rule.parts_ng_price_threshold
        ):
            matched_parts = tuple(ng for ng in rule.parts_ng_words if ng in title_normalized)
            if matched_parts:
                decisions.append(
                    FilterDecision(
                        listing=price,
                        admitted=False,
                        reason=FilterReason.PARTS_NG_WORD_BELOW_THRESHOLD,
                        matched_parts_words=matched_parts,
                    )
                )
                continue

        filtered.append(price)
        decisions.append(FilterDecision(listing=price, admitted=True))

    return FilterResult(rule=rule, admitted=filtered, decisions=decisions)


def exclude_suspicious_prices(
    prices: list[ScrapedPriceT],
    reference_price: int,
    threshold_ratio_min: float,
    threshold_ratio_max: float,
    store_name: str,
    product_name: str,
) -> list[ScrapedPriceT]:
    threshold_min = reference_price * threshold_ratio_min
    threshold_max = reference_price * threshold_ratio_max
    filtered: list[ScrapedPriceT] = []

    for price in prices:
        if price.price < threshold_min or price.price > threshold_max:
            continue
        filtered.append(price)

    return filtered


def filter_by_color_label(
    prices: list[ScrapedPriceT],
    color_label: str,
    color_family: str,
    product_name: str,
    *,
    filter_config: ColorLabelFilterConfig,
    store_name: str = "フリマ",
    has_multiple_black_variants: bool = False,
) -> list[ScrapedPriceT]:
    if color_family == "black" and not has_multiple_black_variants:
        return prices

    color_keywords = {unicodedata.normalize("NFKC", color_label).upper()}
    for kw in filter_config.color_family_keywords.get(color_family, ()):
        color_keywords.add(unicodedata.normalize("NFKC", kw).upper())

    filtered: list[ScrapedPriceT] = []
    for price in prices:
        title = getattr(price, "title", "") or ""
        title_normalized = unicodedata.normalize("NFKC", title).upper()
        if any(kw in title_normalized for kw in color_keywords):
            filtered.append(price)
        else:
            logger.debug(
                "%s: %s (%s) - 色名なしで除外 「%s」",
                store_name,
                product_name,
                color_label,
                f"{title[:50]}..." if len(title) > 50 else title,
            )
    return filtered


def filter_by_product_name_profile(
    prices: list[ScrapedPriceT],
    product_name: str,
    store_name: str,
    *,
    profile: FetcherProfile,
    exclude_product_names: list[str] | None = None,
) -> FilterResult[ScrapedPriceT]:
    """プロファイル定義を使って製品名フィルタを適用する。"""
    base_rule = profile.matching_policy.build_rule(
        product_name=product_name,
        base_rule=profile.product_name_rule,
    )
    effective_rule = ProductNameRule(
        required_keywords=base_rule.required_keywords,
        anchor_keywords=base_rule.anchor_keywords,
        flea_market_ng_words=base_rule.flea_market_ng_words,
        condition_ng_words=base_rule.condition_ng_words,
        partial_item_ng_words=base_rule.partial_item_ng_words,
        parts_ng_words=base_rule.parts_ng_words,
        parts_ng_price_threshold=base_rule.parts_ng_price_threshold,
        exclude_product_names=tuple((*base_rule.exclude_product_names, *(exclude_product_names or []))),
        exclude_yo_titles=base_rule.exclude_yo_titles,
        exclude_empty_box_titles=base_rule.exclude_empty_box_titles,
    )
    return filter_by_product_name_match(
        prices,
        product_name,
        store_name,
        rule=effective_rule,
        matching_policy=profile.matching_policy,
    )


def filter_by_color_label_profile(
    prices: list[ScrapedPriceT],
    color_label: str,
    color_family: str,
    product_name: str,
    *,
    profile: FetcherProfile,
    store_name: str = "フリマ",
    has_multiple_black_variants: bool = False,
) -> list[ScrapedPriceT]:
    """プロファイル定義を使って色ラベルフィルタを適用する。"""
    return filter_by_color_label(
        prices,
        color_label,
        color_family,
        product_name,
        filter_config=profile.color_label_filter,
        store_name=store_name,
        has_multiple_black_variants=has_multiple_black_variants,
    )


class SharedBaseFetcher(ABC, Generic[ProductT, ScrapedPriceT, ConfigT, StoreT]):
    """HTTP / WebDriver を併用する取得基底クラス。"""

    store_type: StoreT
    MAX_SEARCH_RESULTS = 20

    def __init__(self, config: ConfigT, *, webdriver_profile_name: str) -> None:
        self.config: ConfigT = config
        self._webdriver_profile_name = webdriver_profile_name
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self, delay: float = 1.0) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _make_request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> requests.Response | None:
        self._wait_for_rate_limit()
        request_headers = dict(headers or {})

        for attempt in range(max_retries):
            try:
                self._last_request_time = time.time()
                response = self.session.get(url, params=params, headers=request_headers, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def _parse_price(self, price_text: str) -> int | None:
        try:
            cleaned = price_text.replace(",", "").replace("¥", "").replace("円", "")
            cleaned = "".join(c for c in cleaned if c.isdigit())
            if cleaned:
                return int(cleaned)
        except (ValueError, AttributeError):
            pass
        return None

    @contextlib.contextmanager
    def get_webdriver(self) -> Generator[tuple[WebDriver, WebDriverWait], None, None]:
        import selenium.webdriver.support.wait

        from price_platform.platform import browser

        data_path = pathlib.Path(self.config.selenium.data_path)
        driver = browser.create_driver(
            profile_name=self._webdriver_profile_name,
            data_path=data_path,
            is_headless=self.config.selenium.headless,
        )
        wait = selenium.webdriver.support.wait.WebDriverWait(driver, 10)
        try:
            yield driver, wait
        finally:
            browser.quit_driver_gracefully(driver)

    @abstractmethod
    def scrape(self, product: ProductT) -> list[ScrapedPriceT]:
        """商品ごとの価格情報を取得する。"""

    def scrape_with_webdriver(
        self,
        product: ProductT,
        driver: WebDriver,
        wait: WebDriverWait,
    ) -> list[ScrapedPriceT]:
        _ = driver, wait
        return self.scrape(product)

    def scrape_sold_with_webdriver(
        self,
        product: ProductT,
        driver: WebDriver,
        wait: WebDriverWait,
    ) -> list[ScrapedPriceT]:
        _ = product, driver, wait
        return []

    def scrape_all(self, products: list[ProductT]) -> dict[str, list[ScrapedPriceT]]:
        results: dict[str, list[ScrapedPriceT]] = {}
        for product in products:
            try:
                prices = self.scrape(product)
                results[product.name] = prices
            except (requests.RequestException, OSError, ValueError):
                results[product.name] = []
        return results


class ProfiledSharedBaseFetcher(SharedBaseFetcher[ProductT, ScrapedPriceT, ConfigT, StoreT]):
    """取得プロファイルを静的属性として持つ共通取得基底クラス。"""

    FETCHER_PROFILE: ClassVar[FetcherProfile]

    def __init__(self, config: ConfigT) -> None:
        super().__init__(
            config,
            webdriver_profile_name=self.FETCHER_PROFILE.webdriver_profile_name,
        )
