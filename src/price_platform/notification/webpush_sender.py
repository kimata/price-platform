"""Shared Web Push notification sender primitives."""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Protocol, TypeVar

from ..config import WebPushConfig

logger = logging.getLogger(__name__)

# pywebpush (requests) の送信タイムアウト秒。未指定だと無限待ちになり、
# 呼び出し元 (クローラ) を購読者数 × レイテンシ分ブロックする (B11)。
DEFAULT_SEND_TIMEOUT_SEC = 10

# この回数連続で送信に失敗した購読は自動的に無効化する (B12)。
MAX_CONSECUTIVE_FAILURES = 7


class PushSendStatus(Enum):
    """1 件の Web Push 送信結果の種別。"""

    SUCCESS = "success"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class PushSendResult:
    """1 件の Web Push 送信結果。"""

    status: PushSendStatus
    error_message: str | None = None
    status_code: int | None = None

class _PriceEventLike(Protocol):
    """WebPush 送信に必要な最小イベント属性。"""

    event_type: Any
    price: int
    store: Any


EventT = TypeVar("EventT", bound=_PriceEventLike)
ProductT = TypeVar("ProductT")
SubscriptionT = TypeVar("SubscriptionT", bound="SubscriptionProtocol")
StoreT = TypeVar("StoreT", bound="WebPushStoreProtocol")


class SubscriptionProtocol(Protocol):
    """Minimal subscription surface required by the sender."""

    id: int
    endpoint: str
    p256dh_key: str
    auth_key: str


class WebPushStoreProtocol(Protocol[SubscriptionT]):
    """Store operations required by the sender."""

    def get_active_subscriptions_for_event(
        self,
        *,
        group: str | None,
        event_type: str | None,
        product_id: str | None = None,
    ) -> list[SubscriptionT]: ...

    def update_last_used(self, subscription_id: int) -> None: ...

    def mark_expired(self, endpoint: str) -> None: ...

    def record_delivery_failure(self, endpoint: str) -> int: ...

    def record_delivery_success(self, endpoint: str) -> None: ...

    def delete_inactive_subscriptions(self) -> int: ...

    def log_delivery(
        self,
        subscription_id: int,
        event_id: int,
        status: Any,
        error_message: str | None = None,
    ) -> int: ...


class DeliveryStatusProtocol(Protocol):
    """Enum-like delivery status surface required by the sender."""

    SENT: ClassVar[Any]
    FAILED: ClassVar[Any]
    EXPIRED: ClassVar[Any]


def build_detail_url(base_url: str, product_id: str, selection_key: str | None = None) -> str:
    """Build a detail URL with an optional selection key."""
    encoded_id = urllib.parse.quote(product_id, safe="")
    detail_url = f"{base_url.rstrip('/')}/detail/{encoded_id}"
    if selection_key is not None:
        encoded_selection = urllib.parse.quote(selection_key, safe="")
        detail_url = f"{detail_url}/{encoded_selection}"
    return detail_url


@dataclass(frozen=True)
class WebPushPayloadData:
    """通知 payload の data 部。"""

    url: str | None
    product_id: str
    selection_key: str | None
    event_type: str
    price: int
    store: str


@dataclass(frozen=True)
class WebPushPayload:
    """Web Push 通知の payload。"""

    title: str
    body: str
    icon: str | None
    tag: str
    data: WebPushPayloadData

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))


@dataclass
class WebPushResult:
    """Result of a Web Push send operation."""

    success_count: int
    failed_count: int
    expired_count: int


class BaseWebPushSender[EventT: _PriceEventLike, ProductT, StoreT: "WebPushStoreProtocol"]:
    """Shared Web Push sender with app-specific callbacks."""

    def __init__(
        self,
        *,
        config: WebPushConfig,
        store: StoreT,
        delivery_status: DeliveryStatusProtocol,
        external_url: str | None = None,
        product_id_getter: Callable[[ProductT], str],
        product_label_getter: Callable[[ProductT], str],
        product_group_getter: Callable[[ProductT], str | None],
        selection_key_getter: Callable[[EventT, ProductT], str | None],
        fallback_icon_url_getter: Callable[[ProductT], str | None],
    ):
        self._config = config
        self._store = store
        self._delivery_status = delivery_status
        self._external_url = external_url
        self._product_id_getter = product_id_getter
        self._product_label_getter = product_label_getter
        self._product_group_getter = product_group_getter
        self._selection_key_getter = selection_key_getter
        self._fallback_icon_url_getter = fallback_icon_url_getter
        self._vapid_private_key = config.vapid_private_key or None
        if self._vapid_private_key is not None:
            logger.info("VAPID private key configured")

    def build_payload(self, event: EventT, product: ProductT) -> WebPushPayload:
        """Build notification payload for a price event."""
        product_id = self._product_id_getter(product)
        selection_key = self._selection_key_getter(event, product)

        url = None
        icon_url = None
        if self._external_url:
            base_url = self._external_url.rstrip("/")
            encoded_id = urllib.parse.quote(product_id, safe="")
            url = build_detail_url(base_url, product_id, selection_key)
            icon_url = f"{base_url}/api/products/icon/{encoded_id}"

        if icon_url is None:
            icon_url = self._fallback_icon_url_getter(product)

        return WebPushPayload(
            title=f"{event.event_type.emoji} {event.event_type.label}",
            body=f"{self._product_label_getter(product)}\n¥{event.price:,} ({event.store.label})",
            icon=icon_url,
            tag=f"price-{product_id[:50]}",
            data=WebPushPayloadData(
                url=url,
                product_id=product_id,
                selection_key=selection_key,
                event_type=event.event_type.value,
                price=event.price,
                store=event.store.value,
            ),
        )

    def send_to_all(self, event: EventT, product: ProductT) -> WebPushResult:
        """Send a notification to every matching subscription."""
        if not self._config.enabled or self._vapid_private_key is None:
            return WebPushResult(success_count=0, failed_count=0, expired_count=0)

        product_id = self._product_id_getter(product)
        subscriptions = self._store.get_active_subscriptions_for_event(
            group=self._product_group_getter(product),
            event_type=event.event_type.value,
            product_id=product_id,
        )
        if not subscriptions:
            logger.debug("No matching subscriptions for event: %s", event.event_type.value)
            return WebPushResult(success_count=0, failed_count=0, expired_count=0)

        payload_json = self.build_payload(event, product).to_json()
        success_count = 0
        failed_count = 0
        expired_count = 0

        for subscription in subscriptions:
            try:
                result = self._send_push(
                    subscription.endpoint,
                    subscription.p256dh_key,
                    subscription.auth_key,
                    payload_json,
                )
                event_id = getattr(event, "id", None)

                if result.status is PushSendStatus.SUCCESS:
                    success_count += 1
                    self._store.update_last_used(subscription.id)
                    self._store.record_delivery_success(subscription.endpoint)
                    if event_id:
                        self._store.log_delivery(
                            subscription.id, event_id, self._delivery_status.SENT
                        )
                elif result.status is PushSendStatus.EXPIRED:
                    expired_count += 1
                    self._store.mark_expired(subscription.endpoint)
                    if event_id:
                        self._store.log_delivery(
                            subscription.id,
                            event_id,
                            self._delivery_status.EXPIRED,
                            "Subscription expired",
                        )
                else:
                    failed_count += 1
                    self._handle_send_failure(subscription.endpoint, result)
                    if event_id:
                        self._store.log_delivery(
                            subscription.id,
                            event_id,
                            self._delivery_status.FAILED,
                            result.error_message,
                        )
            except sqlite3.Error as exc:
                logger.exception(
                    "Store error while sending push to subscription %d: %s", subscription.id, exc
                )
                failed_count += 1

        logger.info(
            "Web Push sent: success=%d, failed=%d, expired=%d",
            success_count,
            failed_count,
            expired_count,
        )
        self._cleanup_inactive_subscriptions()
        return WebPushResult(
            success_count=success_count,
            failed_count=failed_count,
            expired_count=expired_count,
        )

    def _handle_send_failure(self, endpoint: str, result: PushSendResult) -> None:
        """失敗を記録し、恒久的に失敗し続ける購読を自動無効化する (B12)。

        404/410 以外にも 401/403 (VAPID 鍵不一致等) や恒常的 5xx を返す
        endpoint は復活しないため、連続失敗回数で打ち切る。
        """
        failure_count = self._store.record_delivery_failure(endpoint)
        if failure_count >= MAX_CONSECUTIVE_FAILURES:
            self._store.mark_expired(endpoint)
            logger.warning(
                "連続 %d 回失敗した購読を無効化: %s (最終エラー: %s)",
                failure_count,
                endpoint[:50],
                result.error_message,
            )

    def _cleanup_inactive_subscriptions(self) -> None:
        """無効化済み購読の論理削除行を送信の機会に掃除する (B12)。"""
        try:
            deleted = self._store.delete_inactive_subscriptions()
        except sqlite3.Error:
            logger.exception("Failed to clean up inactive subscriptions")
            return
        if deleted > 0:
            logger.info("Deleted %d inactive Web Push subscriptions", deleted)

    def _send_push(
        self,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        payload: str,
    ) -> PushSendResult:
        """Send a single Web Push notification."""
        try:
            import pywebpush
            import requests
        except ImportError:
            logger.error("pywebpush not installed")
            return PushSendResult(status=PushSendStatus.FAILED, error_message="pywebpush not installed")

        subscription_info = {
            "endpoint": endpoint,
            "keys": {
                "p256dh": p256dh_key,
                "auth": auth_key,
            },
        }
        vapid_claims = {"sub": self._config.vapid_contact}

        try:
            pywebpush.webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._vapid_private_key,
                vapid_claims=vapid_claims,
                timeout=DEFAULT_SEND_TIMEOUT_SEC,
            )
            return PushSendResult(status=PushSendStatus.SUCCESS)
        except pywebpush.WebPushException as exc:
            status_code = None
            if hasattr(exc, "response") and exc.response is not None:
                status_code = exc.response.status_code
                if status_code in (404, 410):
                    logger.info("Subscription expired (HTTP %d): %s", status_code, endpoint[:50])
                    return PushSendResult(status=PushSendStatus.EXPIRED, status_code=status_code)

            logger.warning("WebPush error: %s", exc)
            return PushSendResult(
                status=PushSendStatus.FAILED, error_message=str(exc), status_code=status_code
            )
        except requests.RequestException as exc:
            logger.warning("WebPush transport error: %s", exc)
            return PushSendResult(status=PushSendStatus.FAILED, error_message=str(exc))

    def send_test(self, endpoint: str, p256dh_key: str, auth_key: str) -> bool:
        """Send a test notification to verify a subscription."""
        if not self._config.enabled or self._vapid_private_key is None:
            return False

        payload = json.dumps(
            {
                "title": "通知テスト",
                "body": "Web Push 通知が正常に設定されました",
                "tag": "test-notification",
            }
        )
        result = self._send_push(endpoint, p256dh_key, auth_key, payload)
        return result.status is PushSendStatus.SUCCESS
