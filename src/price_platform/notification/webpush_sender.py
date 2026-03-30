"""Shared Web Push notification sender primitives."""

from __future__ import annotations

import json
import logging
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from ..config import WebPushConfig

logger = logging.getLogger(__name__)

EventT = TypeVar("EventT")
ProductT = TypeVar("ProductT")
SubscriptionT = TypeVar("SubscriptionT", bound="SubscriptionProtocol")
StoreT = TypeVar("StoreT", bound="WebPushStoreProtocol")


class SubscriptionProtocol(Protocol):
    """Minimal subscription surface required by the sender."""

    id: int
    endpoint: str
    p256dh_key: str
    auth_key: str


class DeliveryStatusProtocol(Protocol):
    """Enum-like delivery status surface required by the sender."""

    SENT: Any
    FAILED: Any
    EXPIRED: Any


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

    def log_delivery(
        self,
        subscription_id: int,
        event_id: int,
        status: Any,
        error_message: str | None = None,
    ) -> int: ...


def build_detail_url(base_url: str, product_id: str, selection_key: str | None = None) -> str:
    """Build a detail URL with an optional selection key."""
    encoded_id = urllib.parse.quote(product_id, safe="")
    detail_url = f"{base_url.rstrip('/')}/detail/{encoded_id}"
    if selection_key is not None:
        encoded_selection = urllib.parse.quote(selection_key, safe="")
        detail_url = f"{detail_url}/{encoded_selection}"
    return detail_url


@dataclass
class WebPushResult:
    """Result of a Web Push send operation."""

    success_count: int
    failed_count: int
    expired_count: int


class BaseWebPushSender(Generic[EventT, ProductT, StoreT]):
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

    def build_payload(self, event: EventT, product: ProductT) -> dict[str, object | None]:
        """Build notification payload for a price event."""
        product_id = self._product_id_getter(product)
        selection_key = self._selection_key_getter(event, product)

        url = None
        icon_url = None
        if self._external_url:
            base_url = self._external_url.rstrip("/")
            encoded_id = urllib.parse.quote(product_id, safe="")
            url = build_detail_url(base_url, product_id, selection_key)
            icon_url = f"{base_url}/api/products/ogp-image/{encoded_id}"

        if icon_url is None:
            icon_url = self._fallback_icon_url_getter(product)

        return {
            "title": f"{event.event_type.emoji} {event.event_type.label}",
            "body": f"{self._product_label_getter(product)}\n¥{event.price:,} ({event.store.label})",
            "icon": icon_url,
            "tag": f"price-{product_id[:50]}",
            "data": {
                "url": url,
                "product_id": product_id,
                "selection_key": selection_key,
                "event_type": event.event_type.value,
                "price": event.price,
                "store": event.store.value,
            },
        }

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

        payload_json = json.dumps(self.build_payload(event, product))
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

                if result == "success":
                    success_count += 1
                    self._store.update_last_used(subscription.id)
                    if event_id:
                        self._store.log_delivery(
                            subscription.id, event_id, self._delivery_status.SENT
                        )
                elif result == "expired":
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
                    if event_id:
                        self._store.log_delivery(
                            subscription.id,
                            event_id,
                            self._delivery_status.FAILED,
                            result,
                        )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error sending push to subscription %d: %s", subscription.id, exc)
                failed_count += 1
                event_id = getattr(event, "id", None)
                if event_id:
                    self._store.log_delivery(
                        subscription.id,
                        event_id,
                        self._delivery_status.FAILED,
                        str(exc),
                    )

        logger.info(
            "Web Push sent: success=%d, failed=%d, expired=%d",
            success_count,
            failed_count,
            expired_count,
        )
        return WebPushResult(
            success_count=success_count,
            failed_count=failed_count,
            expired_count=expired_count,
        )

    def _send_push(
        self,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        payload: str,
    ) -> str:
        """Send a single Web Push notification."""
        try:
            import pywebpush
        except ImportError:
            logger.error("pywebpush not installed")
            return "pywebpush not installed"

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
            )
            return "success"
        except pywebpush.WebPushException as exc:
            if hasattr(exc, "response") and exc.response is not None:
                status_code = exc.response.status_code
                if status_code in (404, 410):
                    logger.info("Subscription expired (HTTP %d): %s", status_code, endpoint[:50])
                    return "expired"

            logger.warning("WebPush error: %s", exc)
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error sending push: %s", exc)
            return str(exc)

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
        return self._send_push(endpoint, p256dh_key, auth_key, payload) == "success"
