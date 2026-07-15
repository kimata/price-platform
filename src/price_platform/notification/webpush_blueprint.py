"""Web Push API blueprint ファクトリ (pt-fleama / hp-fleama 共通)。

pt-fleama (grouping = "categories") と hp-fleama (grouping = "makers") では、
「grouping 次元の呼称」とバリデーション用の有効値集合だけが異なり、10 個のルート
本体と WebPushStore の呼び出しは完全に一致している。その共通部を factory 化する。

lens-fleama は WebPushStore の API (update_filters が maker_filter= を取る) と
store 取得経路が異なるため、本 factory の対象外 (lens 側にファイルを残す)。

アプリ側は以下を注入する:
- valid_groups / valid_event_types: バリデーション用の有効値集合
- group_key: JSON で grouping を表すキー名 ("categories" / "makers")
- group_field_name: エラーメッセージ用のフィールド名 ("category" / "maker")
- config_getter: アプリ設定を返す callable (config.notification.webpush.* を参照)
- store_getter: WebPushStore (未設定なら None) を返す callable
- sender_factory: (webpush_config, store) -> テスト通知送信オブジェクト
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import flask
import flask.typing

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _validate_filter_list(
    filter_value: Any,
    valid_set: frozenset[str],
    field_name: str,
) -> tuple[list[str] | None, tuple[flask.Response, int] | None]:
    """フィルターリストをバリデートする.

    Args:
        filter_value: バリデート対象の値
        valid_set: 有効な値の集合
        field_name: エラーメッセージ用のフィールド名

    Returns:
        (バリデート済みリスト or None, エラーレスポンス or None)
    """
    if filter_value is None:
        return None, None
    if not isinstance(filter_value, list):
        return None, (flask.jsonify({"error": f"{field_name} filter must be an array"}), 400)
    for item in filter_value:
        if item not in valid_set:
            return None, (flask.jsonify({"error": f"Invalid {field_name}: {item}"}), 400)
    return filter_value, None


def create_webpush_blueprint(
    *,
    valid_groups: frozenset[str],
    valid_event_types: frozenset[str],
    group_key: str,
    group_field_name: str,
    config_getter: Callable[[], Any],
    store_getter: Callable[[], Any],
    sender_factory: Callable[[Any, Any], Any],
    blueprint_name: str = "webpush_api",
) -> flask.Blueprint:
    """Web Push API の Flask Blueprint を生成する。"""
    blueprint = flask.Blueprint(blueprint_name, __name__)

    def _validate_webpush_filters(
        filters: dict[str, Any],
    ) -> tuple[dict[str, list[str] | None], tuple[flask.Response, int] | None]:
        """WebPush フィルターをバリデートする。"""
        group_values = filters.get("groups", filters.get(group_key))
        group_filter, error = _validate_filter_list(group_values, valid_groups, group_field_name)
        if error:
            return {}, error

        event_type_filter, error = _validate_filter_list(
            filters.get("eventTypes"), valid_event_types, "event type"
        )
        if error:
            return {}, error

        product_filter = filters.get("productIds", filters.get("products"))
        if product_filter is not None and not isinstance(product_filter, list):
            return {}, (flask.jsonify({"error": "products/productIds filter must be an array"}), 400)

        return {
            group_key: group_filter,
            "groups": group_filter,
            "eventTypes": event_type_filter,
            "products": product_filter,
            "productIds": product_filter,
        }, None

    def _handle_store_error(operation: str) -> tuple[flask.Response, int]:
        """ストア操作エラーをハンドルする。"""
        exc_info = sys.exc_info()
        if exc_info[1] is not None and isinstance(exc_info[1], RuntimeError):
            logger.error("WebPushStore not initialized: %s", exc_info[1])
            return flask.jsonify({"error": "Service unavailable"}), 503
        logger.exception("Error %s: %s", operation, exc_info[1])
        return flask.jsonify({"error": "Internal server error"}), 500

    def _require_store() -> Any:
        store = store_getter()
        if store is None:
            raise RuntimeError("WebPushStore not configured")
        return store

    @blueprint.route("/vapid-key", methods=["GET"])
    def get_vapid_key() -> flask.typing.ResponseReturnValue:
        """VAPID 公開鍵を返す。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        public_key = config.notification.webpush.vapid_public_key
        if not public_key:
            return flask.jsonify({"error": "VAPID key not configured"}), 503

        return flask.jsonify({"publicKey": public_key})

    @blueprint.route("/subscribe", methods=["POST"])
    def subscribe() -> flask.typing.ResponseReturnValue:
        """新しい Web Push サブスクリプションを登録する。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        data = flask.request.get_json()
        if not data:
            return flask.jsonify({"error": "Request body is required"}), 400

        endpoint = data.get("endpoint")
        keys = data.get("keys", {})
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")

        if not endpoint or not p256dh or not auth:
            return flask.jsonify({"error": "Missing required fields: endpoint, keys.p256dh, keys.auth"}), 400

        validated_filters, error = _validate_webpush_filters(data.get("filters", {}))
        if error:
            return error

        try:
            store = _require_store()
            subscription_id = store.save_subscription(
                endpoint=endpoint,
                p256dh_key=p256dh,
                auth_key=auth,
                group_filter=validated_filters["groups"],
                event_type_filter=validated_filters["eventTypes"],
                product_filter=validated_filters["products"],
            )

            logger.info("Web Push subscription saved: id=%d", subscription_id)
            return flask.jsonify(
                {
                    "success": True,
                    "subscriptionId": subscription_id,
                }
            )
        except Exception:
            return _handle_store_error("saving subscription")

    @blueprint.route("/unsubscribe", methods=["POST"])
    def unsubscribe() -> flask.typing.ResponseReturnValue:
        """Web Push サブスクリプションを削除する。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        data = flask.request.get_json()
        if not data:
            return flask.jsonify({"error": "Request body is required"}), 400

        endpoint = data.get("endpoint")
        if not endpoint:
            return flask.jsonify({"error": "Missing required field: endpoint"}), 400

        try:
            store = _require_store()
            deleted = store.delete_subscription(endpoint)

            if deleted:
                logger.info("Web Push subscription deleted: endpoint=%s", endpoint[:50])
                return flask.jsonify({"success": True})
            return flask.jsonify({"success": False, "message": "Subscription not found"})
        except Exception:
            return _handle_store_error("deleting subscription")

    @blueprint.route("/filters", methods=["PUT"])
    def update_filters() -> flask.typing.ResponseReturnValue:
        """サブスクリプションのフィルターを更新する。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        data = flask.request.get_json()
        if not data:
            return flask.jsonify({"error": "Request body is required"}), 400

        endpoint = data.get("endpoint")
        if not endpoint:
            return flask.jsonify({"error": "Missing required field: endpoint"}), 400

        validated_filters, error = _validate_webpush_filters(data.get("filters", {}))
        if error:
            return error

        try:
            store = _require_store()
            updated = store.update_filters(
                endpoint,
                group_filter=validated_filters["groups"],
                event_type_filter=validated_filters["eventTypes"],
                product_filter=validated_filters["products"],
            )

            if updated:
                logger.info("Web Push filters updated: endpoint=%s", endpoint[:50])
                return flask.jsonify({"success": True})
            return flask.jsonify({"success": False, "message": "Subscription not found"})
        except Exception:
            return _handle_store_error("updating filters")

    @blueprint.route("/status", methods=["GET"])
    def get_status() -> flask.typing.ResponseReturnValue:
        """エンドポイントのサブスクリプション状態を返す。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        endpoint = flask.request.args.get("endpoint")
        if not endpoint:
            return flask.jsonify({"error": "Missing required query param: endpoint"}), 400

        try:
            store = _require_store()
            subscription = store.get_subscription_by_endpoint(endpoint)

            if subscription is None:
                return flask.jsonify(
                    {
                        "subscribed": False,
                    }
                )

            return flask.jsonify(
                {
                    "subscribed": True,
                    "isActive": subscription.is_active,
                    "filters": {
                        group_key: subscription.group_filter,
                        "groups": subscription.group_filter,
                        "eventTypes": subscription.event_type_filter,
                        "products": subscription.product_filter,
                        "productIds": subscription.product_filter,
                    },
                    "createdAt": subscription.created_at.isoformat(),
                    "lastUsedAt": subscription.last_used_at.isoformat()
                    if subscription.last_used_at
                    else None,
                }
            )
        except Exception:
            return _handle_store_error("getting subscription status")

    @blueprint.route("/product-subscription", methods=["PUT"])
    def update_product_subscription() -> flask.typing.ResponseReturnValue:
        """製品単位のサブスクリプションを追加/削除する。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        data = flask.request.get_json()
        if not data:
            return flask.jsonify({"error": "Request body is required"}), 400

        endpoint = data.get("endpoint")
        product_id = data.get("productId")
        subscribe_flag = data.get("subscribe")

        if not endpoint:
            return flask.jsonify({"error": "Missing required field: endpoint"}), 400
        if not product_id:
            return flask.jsonify({"error": "Missing required field: productId"}), 400
        if subscribe_flag is None:
            return flask.jsonify({"error": "Missing required field: subscribe"}), 400

        try:
            store = _require_store()
            updated = store.update_product_filter(endpoint, product_id, subscribe_flag)

            if updated:
                action = "subscribed to" if subscribe_flag else "unsubscribed from"
                logger.info("Web Push product %s: %s", action, product_id[:50])
                return flask.jsonify({"success": True})
            return flask.jsonify({"success": False, "message": "Subscription not found"})
        except Exception:
            return _handle_store_error("updating product subscription")

    @blueprint.route("/test", methods=["POST"])
    def send_test_notification() -> flask.typing.ResponseReturnValue:
        """現在のサブスクリプションへテスト通知を送信する。"""
        config = config_getter()

        if not config.notification.webpush.enabled:
            return flask.jsonify({"error": "Web Push is not enabled"}), 503

        data = flask.request.get_json()
        if not data:
            return flask.jsonify({"error": "Request body is required"}), 400

        endpoint = data.get("endpoint")
        if not endpoint:
            return flask.jsonify({"error": "Missing required field: endpoint"}), 400

        try:
            store = _require_store()
            subscription = store.get_subscription_by_endpoint(endpoint)

            if subscription is None:
                return flask.jsonify({"error": "Subscription not found"}), 404

            sender = sender_factory(config.notification.webpush, store)
            success = sender.send_test(
                endpoint=subscription.endpoint,
                p256dh_key=subscription.p256dh_key,
                auth_key=subscription.auth_key,
            )

            if success:
                logger.info("Test notification sent successfully")
                return flask.jsonify({"success": True})
            return flask.jsonify({"success": False, "message": "Failed to send test notification"}), 500
        except Exception:
            return _handle_store_error("sending test notification")

    return blueprint
