"""アイテム中心巡回スクレイプエンジンの共通基底。

fleama 3兄弟 (pt / lens / hp) の scrape_engine.py が重複させていた
巡回オーケストレーション・Amazon バッチ・リトライ・ウォームアップ・
しきい値ロードを提供する。

アイテム 1 件を全ストアで処理する `_scrape_item` と、ストア対応判定
`_is_item_applicable` はドメイン固有 (pt/hp は色/バリアント単位のストア処理を
持つ) のため抽象メソッドとしてアプリ側に残す。アプリ間で挙動が異なる点
(メトリクスキー・巡回シャッフル戦略・WebDriver プールのキー・
CI リトライ回数・Amazon バッチ前のチェックポイント) はフックで表現する。
"""

from __future__ import annotations

import logging
import pathlib
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, ClassVar

import my_lib.platform.config
import my_lib.platform.time

from .flea_market_pipeline import FleaMarketPipelineMixin
from .scrape_retry import run_scrape_with_retry

logger = logging.getLogger(__name__)

# エラー時のリトライ待機時間（秒）
ERROR_RETRY_DELAY = 10.0
# アイテム間のスリープ時間（秒）
PRODUCT_INTERVAL_SEC = 10.0
# フリマストア間のスリープ時間（秒）- BOT判定回避
FLEA_MARKET_INTERVAL_SEC = 3.0


def void(fn: Callable[[], object]) -> Callable[[], None]:
    """戻り値を破棄して () -> None に変換する。"""

    def wrapper() -> None:
        fn()

    return wrapper


@dataclass
class ScrapeResult:
    """スクレイピング結果。

    store は各アプリの StoreType enum、prices は各アプリの ScrapedPrice。
    """

    product_id: str
    store: Any
    prices: list[Any]
    success: bool
    error_message: str | None = None
    # このアイテムの最後のストア処理か
    is_last_store_for_product: bool = False
    # 売却済みデータかどうか
    is_sold: bool = False


class BaseScrapeEngine(ABC):
    """アイテム中心の巡回を行うスクレイピングエンジンの基底。

    従来のストア中心の巡回:
        Store A → [Item1, Item2, Item3, ...]
    アイテム中心の巡回（このエンジン）:
        Item1 → [Store A, Store B, Store C, ...]
    これにより、同一ストアへの連続アクセスを避け、BOT判定を回避する。

    サブクラスが定義するもの:
    - ストア集合 ClassVar (WEBDRIVER_STORES / TRUSTED_STORES / FILTERED_STORES /
      FLEA_MARKET_STORES / REFERENCE_PRICE_STORES)
    - amazon_store / dummy_store プロパティ
    - _make_pool() / _make_result() / _scrape_item() / _is_item_applicable()
    - フック: _item_pool_key / _metrics_item_key / _shuffle_items /
      _before_amazon_batch (任意)
    """

    # ストア集合はサブクラスで定義する (各アプリの StoreType enum を使うため)
    WEBDRIVER_STORES: ClassVar[set[Any]]
    TRUSTED_STORES: ClassVar[list[Any]]
    FILTERED_STORES: ClassVar[set[Any]]
    FLEA_MARKET_STORES: ClassVar[set[Any]]
    REFERENCE_PRICE_STORES: ClassVar[list[Any]]

    def __init__(
        self,
        config: Any,
        fetchers: dict[Any, Any] | None = None,
        metrics_manager: Any = None,
        price_store: Any = None,
        checkpoint_callback: Callable[[], None] | None = None,
        ci_mode: bool = False,
    ) -> None:
        self.config = config
        self._fetchers: dict[Any, Any] = fetchers or {}
        self._webdriver_pool: Any = None
        self._metrics_manager = metrics_manager
        self._price_store = price_store
        self._checkpoint_callback = checkpoint_callback
        self._ci_mode = ci_mode
        self._product_interval_sec = 0.0 if ci_mode else PRODUCT_INTERVAL_SEC
        self._flea_market_interval_sec = 0.0 if ci_mode else FLEA_MARKET_INTERVAL_SEC
        self._price_threshold = self._load_price_threshold()

    # --- サブクラスが提供する抽象メンバー -----------------------------------

    @property
    @abstractmethod
    def amazon_store(self) -> Any:
        """アプリの StoreType.AMAZON。"""
        ...

    @property
    @abstractmethod
    def dummy_store(self) -> Any:
        """全ストアスキップ時のダミー結果に使うストア (通常 YODOBASHI)。"""
        ...

    @abstractmethod
    def _make_pool(self) -> Any:
        """アプリの WebDriverPool を生成する。"""
        ...

    @abstractmethod
    def _make_result(
        self,
        *,
        product_id: str,
        store: Any,
        prices: list[Any],
        success: bool,
        error_message: str | None = None,
        is_last_store_for_product: bool = False,
        is_sold: bool = False,
    ) -> Any:
        """アプリの ScrapeResult を生成する。"""
        ...

    @abstractmethod
    def _scrape_item(
        self,
        item: Any,
        target_stores: set[Any],
        pool: Any,
        amazon_prices: dict[str, int] | None = None,
        warmed_up_makers: set[Any] | None = None,
    ) -> list[Any]:
        """1 アイテムを全ストアでスクレイプする (販売中 + 売却済み)。ドメイン固有。"""
        ...

    @abstractmethod
    def _is_item_applicable(self, item: Any, store_type: Any) -> bool:
        """アイテムがストアに対応しているか。ドメイン固有。"""
        ...

    # --- 挙動フック (アプリごとに差がある箇所) -------------------------------

    def _item_pool_key(self, item: Any) -> Any:
        """WebDriver プールのキー (既定は item.maker)。"""
        return item.maker

    def _metrics_item_key(self, item: Any) -> str:
        """メトリクス start_item に渡すアイテムキー (既定は item.name)。"""
        return item.name

    def _shuffle_items(self, items: list[Any]) -> list[Any]:
        """巡回順序のシャッフル (既定はシャッフルなし)。"""
        return list(items)

    def _before_amazon_batch(self) -> None:
        """Amazon バッチ処理直前のフック (既定は何もしない)。"""
        return

    def _default_max_attempts(self) -> int:
        """リトライ回数を明示指定しない場合の既定値 (既定は 2)。

        CI モードで回数を変える等のアプリはオーバーライドする。
        """
        return 2

    # --- 公開 API -----------------------------------------------------------

    def set_fetchers(self, fetchers: dict[Any, Any]) -> None:
        """Set fetchers for all stores."""
        self._fetchers = fetchers

    def add_fetcher(self, store_type: Any, fetcher: Any) -> None:
        """Add a fetcher for a specific store."""
        self._fetchers[store_type] = fetcher

    @contextmanager
    def webdriver_context(self) -> Iterator[Any]:
        """WebDriver プールのコンテキストマネージャ。"""
        pool = self._make_pool()
        self._webdriver_pool = pool
        try:
            yield pool
        finally:
            pool.close_all()
            self._webdriver_pool = None

    def scrape_all(
        self,
        items: list[Any],
        store_filter: set[Any] | None = None,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> list[Any]:
        """全アイテムを全ストアでスクレイプ (内部で WebDriverPool を管理)。"""
        target_stores = set(self._fetchers.keys())
        if store_filter:
            target_stores &= store_filter

        uses_webdriver = bool(target_stores & self.WEBDRIVER_STORES)

        if uses_webdriver:
            with self.webdriver_context() as pool:
                return list(self._scrape_all_items_iter(items, target_stores, pool, shutdown_check))
        return list(self._scrape_all_items_iter(items, target_stores, None, shutdown_check))

    def scrape_all_with_pool(
        self,
        items: list[Any],
        pool: Any,
        store_filter: set[Any] | None = None,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> list[Any]:
        """全アイテムを全ストアでスクレイプ (外部 WebDriverPool 使用)。"""
        return list(self.scrape_iter_with_pool(items, pool, store_filter, shutdown_check))

    def scrape_iter_with_pool(
        self,
        items: list[Any],
        pool: Any,
        store_filter: set[Any] | None = None,
        shutdown_check: Callable[[], bool] | None = None,
        shuffle: bool = False,
    ) -> Iterator[Any]:
        """全アイテムを全ストアでスクレイプ (ジェネレータ版)。"""
        target_stores = set(self._fetchers.keys())
        if store_filter:
            target_stores &= store_filter

        yield from self._scrape_all_items_iter(items, target_stores, pool, shutdown_check, shuffle)

    # --- 内部オーケストレーション -------------------------------------------

    def _scrape_all_items_iter(
        self,
        items: list[Any],
        target_stores: set[Any],
        pool: Any,
        shutdown_check: Callable[[], bool] | None = None,
        shuffle: bool = False,
    ) -> Iterator[Any]:
        """全アイテムをスクレイプ (ジェネレータ版)。

        Amazon は API 呼び出し回数を抑えるため、最初に全アイテムをまとめて処理する。
        その後、各アイテムを他のストアでスクレイプし、1 アイテム処理するごとに yield。
        """
        if shutdown_check and shutdown_check():
            logger.info("シャットダウンが要求されたため、スクレイプを中断します")
            return

        amazon_prices: dict[str, int] = {}

        remaining_stores = target_stores - {self.amazon_store}
        amazon_only = not remaining_stores

        if self.amazon_store in target_stores:
            for result in self._scrape_amazon_batch(items, shutdown_check):
                if amazon_only:
                    result = replace(result, is_last_store_for_product=True)
                yield result
                if result.prices:
                    amazon_prices[result.product_id] = min(p.price for p in result.prices)

        if shutdown_check and shutdown_check():
            logger.info("シャットダウンが要求されたため、スクレイプを中断します")
            return

        if amazon_only:
            return

        items_to_process = self._shuffle_items(items) if shuffle else list(items)

        warmed_up_makers: set[Any] = set()

        for item in items_to_process:
            if shutdown_check and shutdown_check():
                logger.info("シャットダウンが要求されたため、スクレイプを中断します")
                return

            item_results = self._scrape_item(
                item, remaining_stores, pool, amazon_prices, warmed_up_makers
            )

            if item_results:
                item_results[-1] = replace(item_results[-1], is_last_store_for_product=True)
            else:
                item_results.append(
                    self._make_result(
                        product_id=item.id,
                        store=self.dummy_store,
                        prices=[],
                        success=True,
                        is_last_store_for_product=True,
                    )
                )

            yield from item_results

            if self._product_interval_sec > 0:
                time.sleep(self._product_interval_sec)

    def _scrape_amazon_batch(
        self,
        items: list[Any],
        shutdown_check: Callable[[], bool] | None = None,
    ) -> list[Any]:
        """Amazon を全アイテムに対してバッチ処理する。

        Creators API は1回の呼び出しで10件まで取得可能。エラー時は待機してリトライ。
        """
        results: list[Any] = []
        fetcher = self._fetchers.get(self.amazon_store)
        if fetcher is None:
            return results

        # Creators API セッション結果をクリア（巡回開始時）
        clear_session = getattr(fetcher, "clear_paapi_session", None)
        if callable(clear_session):
            clear_session()

        if shutdown_check and shutdown_check():
            return results

        items_with_asin = [
            item for item in items if self._is_item_applicable(item, self.amazon_store)
        ]
        if not items_with_asin:
            return results

        logger.info(f"Amazon バッチ処理開始: {len(items_with_asin)}件の商品")

        # バッチ処理は長時間ブロックしうるため、開始直前のフック (liveness 更新等)
        self._before_amazon_batch()

        price_map: dict[str, list[Any]] = {}
        last_error: Exception | None = None

        batch_started_at = my_lib.platform.time.now()
        batch_start_time = time.perf_counter()

        # 最大2回試行（初回 + リトライ1回）
        for attempt in range(2):
            try:
                price_map = fetcher.scrape_all(items_with_asin)
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt == 0:
                    logger.warning(f"Amazon バッチ処理エラー、{ERROR_RETRY_DELAY}秒後にリトライ: {e}")
                    time.sleep(ERROR_RETRY_DELAY)
                else:
                    logger.error(f"❌ Amazon バッチ処理リトライ失敗: {e}")

        batch_duration = time.perf_counter() - batch_start_time
        if self._metrics_manager:
            self._metrics_manager.record_amazon_batch(
                started_at=batch_started_at,
                duration_sec=batch_duration,
                product_ids=[item.id for item in items_with_asin],
                success=(last_error is None),
                error_message=str(last_error) if last_error else None,
            )

        for item in items_with_asin:
            prices = price_map.get(item.name, [])
            results.append(
                self._make_result(
                    product_id=item.id,
                    store=self.amazon_store,
                    prices=prices,
                    success=(last_error is None),
                    error_message=str(last_error) if last_error else None,
                )
            )
            if prices:
                min_price = min(p.price for p in prices)
                logger.info(f"amazon: {item.name} - {len(prices)}件、最安 ¥{min_price:,}")

        logger.info(f"Amazon バッチ処理完了: {len(results)}件")
        return results

    # --- リトライ付きスクレイプ ---------------------------------------------

    def _scrape_with_retry(
        self,
        item: Any,
        store_type: Any,
        fetcher: Any,
        pool: Any,
        max_attempts: int | None = None,
    ) -> Any:
        """リトライ付きでスクレイプする。"""
        if max_attempts is None:
            max_attempts = self._default_max_attempts()
        item_timing = None
        if self._metrics_manager:
            item_timing = self._metrics_manager.start_item(store_type.value, self._metrics_item_key(item))

        uses_webdriver = store_type in self.WEBDRIVER_STORES and pool is not None
        maker = self._item_pool_key(item)
        outcome = run_scrape_with_retry(
            execute=(
                lambda: self._scrape_with_webdriver(item, fetcher, pool)
                if uses_webdriver and pool is not None
                else fetcher.scrape(item)
            ),
            store_name=store_type.value,
            item_name=item.name,
            max_attempts=max_attempts,
            retry_delay_sec=ERROR_RETRY_DELAY,
            item_timing=item_timing,
            on_timeout=void(lambda: pool.notify_timeout(maker))
            if uses_webdriver and pool is not None
            else None,
            on_success=void(lambda: pool.notify_success(maker))
            if uses_webdriver and pool is not None
            else None,
        )

        return self._make_result(
            product_id=item.id,
            store=store_type,
            prices=outcome.prices,
            success=outcome.success,
            error_message=outcome.error_message,
        )

    def _scrape_with_webdriver(self, item: Any, fetcher: Any, pool: Any) -> list[Any]:
        """ブラウザページを使用してスクレイプする。"""
        page = pool.get(self._item_pool_key(item))
        return fetcher.scrape_with_webdriver(item, page)

    def _scrape_sold_with_retry(
        self,
        item: Any,
        store_type: Any,
        fetcher: Any,
        pool: Any,
        max_attempts: int | None = None,
    ) -> Any:
        """リトライ付きで売却済みアイテムをスクレイプする。"""
        if max_attempts is None:
            max_attempts = self._default_max_attempts()
        store_name = f"{store_type.value}_sold"
        item_timing = None
        if self._metrics_manager:
            item_timing = self._metrics_manager.start_item(store_name, self._metrics_item_key(item))

        maker = self._item_pool_key(item)
        outcome = run_scrape_with_retry(
            execute=lambda: fetcher.scrape_sold_with_webdriver(item, pool.get(maker)),
            store_name=store_name,
            item_name=item.name,
            max_attempts=max_attempts,
            retry_delay_sec=ERROR_RETRY_DELAY,
            item_timing=item_timing,
            on_timeout=void(lambda: pool.notify_timeout(maker)),
            on_success=void(lambda: pool.notify_success(maker)),
        )

        return self._make_result(
            product_id=item.id,
            store=store_type,
            prices=outcome.prices,
            success=outcome.success,
            error_message=outcome.error_message,
            is_sold=True,
        )

    def _warmup_flea_markets(self, maker: Any, pool: Any) -> None:
        """フリマストアのウォームアップを実行する (メーカー/カテゴリごとに1回)。

        Google 検索経由で各フリマサイトにアクセスし、Cookie/セッションを確立する。
        """
        page = pool.get(maker)
        for store_type in self.FLEA_MARKET_STORES:
            fetcher = self._fetchers.get(store_type)
            if isinstance(fetcher, FleaMarketPipelineMixin):
                if fetcher.warmup(page):
                    logger.info(f"{store_type.value}: ウォームアップ完了 ({maker.value})")
                else:
                    logger.warning(f"{store_type.value}: ウォームアップ失敗 ({maker.value})")

    # --- 基準価格ロード -----------------------------------------------------

    def _load_price_threshold(self) -> dict[str, int]:
        """price_threshold.yaml から最低基準価格を読み込む。"""
        threshold_path = self._price_threshold_yaml_path()
        if threshold_path is None or not threshold_path.exists():
            logger.info("price_threshold.yaml not found, using empty threshold")
            return {}

        try:
            data = my_lib.platform.config.load(
                threshold_path,
                self._price_threshold_schema_path(),
                include_base_dir=False,
            )
            if data is None or not isinstance(data, list):
                return {}
            return self._parse_price_threshold(data)
        except (OSError, ValueError) as e:
            logger.warning(f"Failed to load price_threshold.yaml: {e}")
            return {}

    def _price_threshold_yaml_path(self) -> pathlib.Path | None:
        """price_threshold.yaml の場所 (アプリでオーバーライド)。"""
        return None

    def _price_threshold_schema_path(self) -> pathlib.Path | None:
        """price_threshold.schema の場所 (アプリでオーバーライド)。"""
        return None

    def _parse_price_threshold(self, data: list[Any]) -> dict[str, int]:
        """price_threshold.yaml の内容を name→price_min の辞書へ変換する。

        既定は {"name", "price_min"} のフラットな辞書リストを想定。
        アプリ固有の dataclass を使う場合はオーバーライドする。
        """
        result: dict[str, int] = {}
        for entry in data:
            if isinstance(entry, dict) and "name" in entry and "price_min" in entry:
                result[entry["name"]] = entry["price_min"]
        return result

    def _get_historical_reference_price(self, item_name: str) -> int | None:
        """price_store から過去の信頼ストア価格の最安値を取得する。"""
        if self._price_store is None:
            return None
        return self._price_store.get_lowest_price_by_stores(
            item_name,
            self.REFERENCE_PRICE_STORES,
        )
