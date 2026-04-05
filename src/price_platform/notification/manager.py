"""通知マネージャーの共通実装。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from price_platform.config import TwitterConfig
from price_platform.social_posts import SocialCopyMetadata, SocialPostContext, compose_social_post

from .webpush_sender import WebPushResult, build_detail_url

logger = logging.getLogger(__name__)

class _NotificationConfigLike(Protocol):
    """通知マネージャーが必要とする最小設定インターフェース。"""

    @property
    def notification(self) -> Any: ...

    @property
    def webapp(self) -> Any: ...

    def get_absolute_path(self, relative_path: Any) -> Path: ...


class _NotifiableEventLike(Protocol):
    """通知マネージャーが必要とする最小イベントインターフェース。"""

    @property
    def twitter_enabled(self) -> bool: ...

    @property
    def event_type(self) -> Any: ...

    @property
    def product_id(self) -> str: ...

    @property
    def price(self) -> int: ...

    @property
    def store(self) -> Any: ...

    def format_message(self, product_name: str) -> str: ...


ConfigT = TypeVar("ConfigT", bound=_NotificationConfigLike)
EventT = TypeVar("EventT", bound=_NotifiableEventLike)
ProductT = TypeVar("ProductT")
CatalogT = TypeVar("CatalogT")
NotificationStoreT = TypeVar("NotificationStoreT", bound="NotificationStoreProtocol[Any]")
TwitterPosterT = TypeVar("TwitterPosterT", bound="TwitterPosterProtocol")
WebPushStoreT = TypeVar("WebPushStoreT")
WebPushSenderT = TypeVar("WebPushSenderT", bound="WebPushSenderProtocol[Any, Any]")

_EventT_contra = TypeVar("_EventT_contra", contravariant=True)
_ProductT_contra = TypeVar("_ProductT_contra", contravariant=True)


class NotificationStoreProtocol(Protocol[_EventT_contra]):
    """通知ストアに必要な最小インターフェース。"""

    def enqueue(self, event_or_payload: _EventT_contra, message: str | None = None) -> object: ...


class TwitterPosterProtocol(Protocol):
    """投稿ワーカーに必要な最小インターフェース。"""

    @property
    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def notify_new_item(self) -> None: ...


class WebPushSenderProtocol(Protocol[_EventT_contra, _ProductT_contra]):
    """Web Push 送信クラスに必要な最小インターフェース。"""

    def send_to_all(self, event: _EventT_contra, product: _ProductT_contra) -> WebPushResult: ...


@dataclass(frozen=True)
class SelectionKeyStrategy(Generic[EventT, ProductT]):
    """通知リンクの selection key を解決する戦略。"""

    resolve: Callable[[EventT, ProductT | None], str | None]


@dataclass(frozen=True)
class ProductLineStrategy(Generic[EventT, ProductT]):
    """通知文面用の商品名行を組み立てる戦略。"""

    build: Callable[[ProductT, EventT], str]


@dataclass(frozen=True)
class SocialCopyStrategy(Generic[ProductT]):
    """SNS 投稿向け補足文言を組み立てる戦略。"""

    build: Callable[[ProductT], SocialCopyMetadata]


@dataclass(frozen=True)
class NotificationStrategies(Generic[EventT, ProductT]):
    """通知文面生成に使う差し替え戦略群。"""

    selection_key: SelectionKeyStrategy[EventT, ProductT]
    product_line: ProductLineStrategy[EventT, ProductT]
    social_copy: SocialCopyStrategy[ProductT]


@dataclass(frozen=True)
class NotificationPresentation(Generic[EventT, ProductT, CatalogT]):
    """通知文面生成に必要なアプリ差分をまとめた定義。"""

    resolve_product: Callable[[CatalogT, str], ProductT | None]
    product_name_getter: Callable[[ProductT], str]
    strategies: NotificationStrategies[EventT, ProductT]


@dataclass(frozen=True)
class NotificationRuntime(Generic[NotificationStoreT, TwitterPosterT, WebPushStoreT, WebPushSenderT]):
    """通知ランタイムの生成関数群。"""

    open_notification_store: Callable[[Path], NotificationStoreT]
    create_twitter_poster: Callable[[TwitterConfig, NotificationStoreT], TwitterPosterT]
    open_webpush_store: Callable[[Path], WebPushStoreT]
    create_webpush_sender: Callable[[Any, WebPushStoreT, str | None], WebPushSenderT]


def build_twitter_config(config: Any) -> TwitterConfig:
    """設定から共有 Twitter 設定を生成する。"""
    return TwitterConfig(
        enabled=config.enabled,
        api_key=config.api_key,
        api_secret=config.api_secret,
        access_token=config.access_token,
        access_token_secret=config.access_token_secret,
        post_interval_sec=config.post_interval_sec,
    )


def build_notification_runtime(
    *,
    open_notification_store: Callable[[Path], NotificationStoreT],
    create_twitter_poster: Callable[[TwitterConfig, NotificationStoreT], TwitterPosterT],
    open_webpush_store: Callable[[Path], WebPushStoreT],
    webpush_sender_factory: Callable[..., WebPushSenderT],
) -> NotificationRuntime[NotificationStoreT, TwitterPosterT, WebPushStoreT, WebPushSenderT]:
    """通知 runtime を標準形で構築する。"""
    return NotificationRuntime(
        open_notification_store=open_notification_store,
        create_twitter_poster=create_twitter_poster,
        open_webpush_store=open_webpush_store,
        create_webpush_sender=lambda config, store, external_url: webpush_sender_factory(
            config=config,
            store=store,
            external_url=external_url,
        ),
    )


def build_social_message(
    event: EventT,
    product: ProductT,
    external_url: str,
    strategies: NotificationStrategies[EventT, ProductT],
) -> str:
    """戦略群を使って SNS 投稿文面を組み立てる。"""
    selection_key = strategies.selection_key.resolve(event, product)
    detail_url = build_detail_url(external_url, getattr(event, "product_id"), selection_key)
    post = compose_social_post(
        SocialPostContext(
            product_id=getattr(event, "product_id"),
            product_line=strategies.product_line.build(product, event),
            detail_url=detail_url,
            event_type_value=getattr(getattr(event, "event_type"), "value"),
            event_type_label=getattr(getattr(event, "event_type"), "label"),
            event_emoji=getattr(getattr(event, "event_type"), "emoji"),
            store_label=getattr(getattr(event, "store"), "label"),
            price=getattr(event, "price"),
            previous_price=getattr(event, "previous_price"),
            reference_price=getattr(event, "reference_price"),
            change_percent=getattr(event, "change_percent"),
            period_days=getattr(event, "period_days"),
            recorded_at=getattr(event, "recorded_at"),
            hashtag=getattr(product, "hashtag"),
            social_copy=strategies.social_copy.build(product),
        )
    )
    return post.message


@dataclass
class BaseNotificationManager(
    Generic[
        ConfigT,
        EventT,
        ProductT,
        CatalogT,
        NotificationStoreT,
        TwitterPosterT,
        WebPushStoreT,
        WebPushSenderT,
    ]
):
    """通知ストア、投稿ワーカー、Web Push の共通ライフサイクル管理。"""

    config: ConfigT
    presentation: NotificationPresentation[EventT, ProductT, CatalogT]
    runtime: NotificationRuntime[NotificationStoreT, TwitterPosterT, WebPushStoreT, WebPushSenderT]
    _store: NotificationStoreT | None = field(default=None, repr=False)
    _poster: TwitterPosterT | None = field(default=None, repr=False)
    _catalog_getter: Callable[[], CatalogT] | None = field(default=None, repr=False)
    _webpush_store: WebPushStoreT | None = field(default=None, repr=False)
    _webpush_sender: WebPushSenderT | None = field(default=None, repr=False)

    def start(self, catalog_getter: Callable[[], CatalogT]) -> None:
        """通知機能を起動する。"""
        if not self.config.notification.enabled:
            logger.info("通知機能は無効です")
            return

        self._catalog_getter = catalog_getter

        db_path = self.config.get_absolute_path(self.config.notification.db_path)
        self._store = self.runtime.open_notification_store(db_path)
        logger.info("通知ストアを初期化: %s", db_path)

        if self.config.notification.twitter.enabled:
            twitter_config = build_twitter_config(self.config.notification.twitter)
            self._poster = self.runtime.create_twitter_poster(twitter_config, self._store)
            self._poster.start()
            logger.info("Twitter投稿ワーカーを起動")

        if self.config.notification.webpush.enabled:
            webpush_db_path = self.config.get_absolute_path(self.config.notification.webpush.db_path)
            self._webpush_store = self.runtime.open_webpush_store(webpush_db_path)
            logger.info("Web Push ストアを初期化: %s", webpush_db_path)

            self._webpush_sender = self.runtime.create_webpush_sender(
                self.config.notification.webpush,
                self._webpush_store,
                self.config.webapp.external_url,
            )
            logger.info("Web Push sender を初期化")

    def stop(self) -> None:
        """通知機能を停止する。"""
        if self._poster is not None:
            self._poster.stop()
            self._poster = None
            logger.info("Twitter投稿ワーカーを停止")

        if self._webpush_sender is not None:
            self._webpush_sender = None
            logger.info("Web Push sender を停止")

        self._webpush_store = None
        self._store = None
        self._catalog_getter = None

    def enqueue(self, event: EventT) -> None:
        """価格イベントを通知キューに登録する。"""
        if self._store is None:
            return

        if not event.twitter_enabled:
            logger.debug("通知スキップ（対象外）: %s - %s", event.event_type.label, event.product_id)
            return

        product = self._resolve_product(event)
        display_name = (
            self.presentation.product_name_getter(product)
            if product is not None
            else event.product_id
        )
        message = f"{event.event_type.emoji} {event.format_message(display_name)}"

        if product is not None and self.config.webapp.external_url:
            message = build_social_message(
                event,
                product,
                self.config.webapp.external_url,
                self.presentation.strategies,
            )

        self._store.enqueue(event, message)
        logger.info("通知キューに追加: %s - %s", event.event_type.label, event.product_id)

        if self._poster is not None:
            self._poster.notify_new_item()

        if self._webpush_sender is not None and product is not None:
            result = self._webpush_sender.send_to_all(event, product)
            self._log_webpush_result(result)

    def _resolve_product(self, event: EventT) -> ProductT | None:
        if self._catalog_getter is None:
            return None
        catalog = self._catalog_getter()
        return self.presentation.resolve_product(catalog, event.product_id)

    def _log_webpush_result(self, result: WebPushResult) -> None:
        if result.success_count > 0 or result.failed_count > 0 or result.expired_count > 0:
            logger.info(
                "Web Push 送信: 成功=%d, 失敗=%d, 期限切れ=%d",
                result.success_count,
                result.failed_count,
                result.expired_count,
            )

    @property
    def is_running(self) -> bool:
        """投稿ワーカーが動作中かを返す。"""
        return self._poster is not None and self._poster.is_running

    @property
    def store(self) -> NotificationStoreT | None:
        """通知ストアを返す。"""
        return self._store

    @property
    def poster(self) -> TwitterPosterT | None:
        """投稿ワーカーを返す。"""
        return self._poster
