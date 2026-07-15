"""price_platform.notification.webpush_blueprint のユニットテスト。

grouping 次元を "categories" として具象化し、10 ルートの挙動 (バリデーション・
store 呼び出し・エラーハンドリング) を検証する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import flask
import pytest

from price_platform.notification.webpush_blueprint import create_webpush_blueprint

VALID_GROUPS = frozenset(["impact_drivers", "circular_saws"])
VALID_EVENT_TYPES = frozenset(["all_time_low", "flea_bargain"])


@dataclass
class WebpushConf:
    enabled: bool = True
    vapid_public_key: str = "PUBKEY"


@dataclass
class NotificationConf:
    webpush: WebpushConf


@dataclass
class AppConf:
    notification: NotificationConf


@dataclass
class FakeSubscription:
    endpoint: str = "https://push.example/ep"
    p256dh_key: str = "p256"
    auth_key: str = "auth"
    is_active: bool = True
    group_filter: list[str] | None = None
    event_type_filter: list[str] | None = None
    product_filter: list[str] | None = None
    created_at: datetime = datetime(2026, 1, 1, 0, 0, 0)
    last_used_at: datetime | None = None


class FakeStore:
    def __init__(self):
        self.calls: list[tuple] = []
        self.subscription: FakeSubscription | None = None
        self.save_result = 42
        self.delete_result = True
        self.update_result = True
        self.product_result = True
        self.raise_runtime = False

    def _maybe_raise(self):
        if self.raise_runtime:
            raise RuntimeError("boom")

    def save_subscription(self, **kwargs):
        self._maybe_raise()
        self.calls.append(("save_subscription", kwargs))
        return self.save_result

    def delete_subscription(self, endpoint):
        self.calls.append(("delete_subscription", endpoint))
        return self.delete_result

    def update_filters(self, endpoint, **kwargs):
        self.calls.append(("update_filters", endpoint, kwargs))
        return self.update_result

    def get_subscription_by_endpoint(self, endpoint):
        self.calls.append(("get_subscription_by_endpoint", endpoint))
        return self.subscription

    def update_product_filter(self, endpoint, product_id, subscribe):
        self.calls.append(("update_product_filter", endpoint, product_id, subscribe))
        return self.product_result


class FakeSender:
    def __init__(self):
        self.result = True
        self.calls: list[dict] = []

    def send_test(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def config():
    return AppConf(notification=NotificationConf(webpush=WebpushConf()))


@pytest.fixture
def client(store, sender, config):
    holder = {"config": config, "store": store, "sender": sender}

    blueprint = create_webpush_blueprint(
        valid_groups=VALID_GROUPS,
        valid_event_types=VALID_EVENT_TYPES,
        group_key="categories",
        group_field_name="category",
        config_getter=lambda: holder["config"],
        store_getter=lambda: holder["store"],
        sender_factory=lambda _conf, _store: holder["sender"],
    )
    app = flask.Flask(__name__)
    app.register_blueprint(blueprint, url_prefix="/api/webpush")
    app.config["holder"] = holder
    return app.test_client()


class TestVapidKey:
    def test_returns_public_key(self, client):
        resp = client.get("/api/webpush/vapid-key")
        assert resp.status_code == 200
        assert resp.get_json() == {"publicKey": "PUBKEY"}

    def test_disabled_returns_503(self, client, config):
        config.notification.webpush.enabled = False
        resp = client.get("/api/webpush/vapid-key")
        assert resp.status_code == 503

    def test_missing_key_returns_503(self, client, config):
        config.notification.webpush.vapid_public_key = ""
        resp = client.get("/api/webpush/vapid-key")
        assert resp.status_code == 503


class TestSubscribe:
    def _body(self, **overrides):
        body = {
            "endpoint": "https://push.example/ep",
            "keys": {"p256dh": "p256", "auth": "auth"},
            "filters": {"categories": ["impact_drivers"], "eventTypes": ["all_time_low"]},
        }
        body.update(overrides)
        return body

    def test_success(self, client, store):
        resp = client.post("/api/webpush/subscribe", json=self._body())
        assert resp.status_code == 200
        assert resp.get_json() == {"success": True, "subscriptionId": 42}
        name, kwargs = store.calls[0]
        assert name == "save_subscription"
        assert kwargs["group_filter"] == ["impact_drivers"]
        assert kwargs["event_type_filter"] == ["all_time_low"]

    def test_groups_alias_accepted(self, client, store):
        resp = client.post(
            "/api/webpush/subscribe",
            json=self._body(filters={"groups": ["circular_saws"]}),
        )
        assert resp.status_code == 200
        assert store.calls[0][1]["group_filter"] == ["circular_saws"]

    def test_missing_fields_returns_400(self, client):
        resp = client.post("/api/webpush/subscribe", json={"endpoint": "x", "keys": {}})
        assert resp.status_code == 400

    def test_invalid_group_returns_400(self, client):
        resp = client.post(
            "/api/webpush/subscribe",
            json=self._body(filters={"categories": ["not_a_group"]}),
        )
        assert resp.status_code == 400
        assert "Invalid category" in resp.get_json()["error"]

    def test_invalid_event_type_returns_400(self, client):
        resp = client.post(
            "/api/webpush/subscribe",
            json=self._body(filters={"eventTypes": ["bogus"]}),
        )
        assert resp.status_code == 400

    def test_non_list_filter_returns_400(self, client):
        resp = client.post(
            "/api/webpush/subscribe",
            json=self._body(filters={"categories": "impact_drivers"}),
        )
        assert resp.status_code == 400

    def test_store_error_returns_503(self, client, store):
        store.raise_runtime = True
        resp = client.post("/api/webpush/subscribe", json=self._body())
        assert resp.status_code == 503

    def test_store_none_returns_503(self, client):
        client.application.config["holder"]["store"] = None
        resp = client.post("/api/webpush/subscribe", json=self._body())
        assert resp.status_code == 503


class TestUnsubscribe:
    def test_success(self, client, store):
        resp = client.post("/api/webpush/unsubscribe", json={"endpoint": "ep"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert store.calls[0] == ("delete_subscription", "ep")

    def test_not_found(self, client, store):
        store.delete_result = False
        resp = client.post("/api/webpush/unsubscribe", json={"endpoint": "ep"})
        assert resp.get_json()["success"] is False

    def test_missing_endpoint_returns_400(self, client):
        resp = client.post("/api/webpush/unsubscribe", json={})
        assert resp.status_code == 400


class TestUpdateFilters:
    def test_success(self, client, store):
        resp = client.put(
            "/api/webpush/filters",
            json={"endpoint": "ep", "filters": {"categories": ["impact_drivers"]}},
        )
        assert resp.status_code == 200
        name, endpoint, kwargs = store.calls[0]
        assert name == "update_filters"
        assert endpoint == "ep"
        assert kwargs["group_filter"] == ["impact_drivers"]

    def test_missing_endpoint_returns_400(self, client):
        resp = client.put("/api/webpush/filters", json={"filters": {}})
        assert resp.status_code == 400


class TestStatus:
    def test_not_subscribed(self, client):
        resp = client.get("/api/webpush/status?endpoint=ep")
        assert resp.status_code == 200
        assert resp.get_json() == {"subscribed": False}

    def test_subscribed(self, client, store):
        store.subscription = FakeSubscription(
            group_filter=["impact_drivers"],
            event_type_filter=["all_time_low"],
            product_filter=["p1"],
        )
        resp = client.get("/api/webpush/status?endpoint=ep")
        data = resp.get_json()
        assert data["subscribed"] is True
        assert data["filters"]["categories"] == ["impact_drivers"]
        assert data["filters"]["groups"] == ["impact_drivers"]
        assert data["filters"]["eventTypes"] == ["all_time_low"]
        assert data["createdAt"] == "2026-01-01T00:00:00"
        assert data["lastUsedAt"] is None

    def test_missing_endpoint_returns_400(self, client):
        resp = client.get("/api/webpush/status")
        assert resp.status_code == 400


class TestProductSubscription:
    def test_success(self, client, store):
        resp = client.put(
            "/api/webpush/product-subscription",
            json={"endpoint": "ep", "productId": "makita-td002g", "subscribe": True},
        )
        assert resp.status_code == 200
        assert store.calls[0] == ("update_product_filter", "ep", "makita-td002g", True)

    def test_missing_product_returns_400(self, client):
        resp = client.put(
            "/api/webpush/product-subscription",
            json={"endpoint": "ep", "subscribe": True},
        )
        assert resp.status_code == 400

    def test_missing_subscribe_returns_400(self, client):
        resp = client.put(
            "/api/webpush/product-subscription",
            json={"endpoint": "ep", "productId": "x"},
        )
        assert resp.status_code == 400


class TestSendTest:
    def test_success(self, client, store, sender):
        store.subscription = FakeSubscription()
        resp = client.post("/api/webpush/test", json={"endpoint": "ep"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert sender.calls[0]["endpoint"] == "https://push.example/ep"

    def test_subscription_not_found_returns_404(self, client):
        resp = client.post("/api/webpush/test", json={"endpoint": "ep"})
        assert resp.status_code == 404

    def test_send_failure_returns_500(self, client, store, sender):
        store.subscription = FakeSubscription()
        sender.result = False
        resp = client.post("/api/webpush/test", json={"endpoint": "ep"})
        assert resp.status_code == 500
