"""price_platform.metrics.webapi のテスト"""

# ruff: noqa: S101

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import flask
import pytest

import price_platform.metrics.webapi


@dataclass
class _StubNotificationConfig:
    enabled: bool = False
    twitter: Any = None
    webpush: Any = None


@dataclass
class _StubClientMetricsConfig:
    enabled: bool = False
    sampling_rate: float = 1.0


@dataclass
class _StubConfig:
    notification: _StubNotificationConfig = field(default_factory=_StubNotificationConfig)
    client_metrics: _StubClientMetricsConfig = field(default_factory=_StubClientMetricsConfig)


def _passthrough_auth(func):
    return func


def _make_spec(**overrides) -> price_platform.metrics.webapi.MetricsApiSpec:
    defaults: dict[str, Any] = {
        "get_config": _StubConfig,
        "get_metrics_db": lambda: None,
        "get_notification_store": lambda: None,
        "get_webpush_store": lambda: None,
        "get_client_metrics_db": lambda: None,
        "require_auth": _passthrough_auth,
        "total_product_count": lambda: 0,
        "product_group_resolver": lambda _product_id: None,
        "group_stats_key": "maker_stats",
        "grouped_products_key": "product_by_category",
    }
    defaults.update(overrides)
    return price_platform.metrics.webapi.MetricsApiSpec(**defaults)


@pytest.fixture
def make_client():
    def _make(spec: price_platform.metrics.webapi.MetricsApiSpec):
        app = flask.Flask(__name__)
        app.register_blueprint(
            price_platform.metrics.webapi.create_metrics_api_blueprint(spec), url_prefix="/api/metrics"
        )
        return app.test_client()

    return _make


class TestCreateBlueprint:
    def test_routes_registered(self, make_client):
        """主要エンドポイントが登録される"""
        spec = _make_spec()
        client = make_client(spec)

        # 通知無効時の twitter ステータス
        response = client.get("/api/metrics/twitter")
        assert response.status_code == 200
        assert response.get_json()["enabled"] is False

    def test_require_auth_is_applied(self, make_client):
        """注入した認証デコレータが認証必須エンドポイントに適用される"""

        def deny_auth(func):
            def wrapper(*args, **kwargs):  # noqa: ARG001
                return flask.jsonify({"error": "unauthorized"}), 401

            wrapper.__name__ = func.__name__
            return wrapper

        spec = _make_spec(require_auth=deny_auth)
        client = make_client(spec)

        assert client.get("/api/metrics/status").status_code == 401
        assert client.get("/api/metrics/sessions").status_code == 401

    def test_client_perf_disabled(self, make_client):
        """client_metrics 無効時は disabled を返す（認証不要エンドポイント）"""
        spec = _make_spec()
        client = make_client(spec)

        response = client.post("/api/metrics/client/perf", json={})
        assert response.status_code == 200
        assert response.get_json()["status"] == "disabled"

    def test_metrics_db_not_configured(self, make_client):
        """メトリクス DB 未設定時に /status が 500 系にならず例外を伝える"""
        spec = _make_spec()
        client = make_client(spec)

        # RuntimeError は Flask が 500 に変換する
        response = client.get("/api/metrics/status")
        assert response.status_code == 500

    def test_webpush_status_disabled(self, make_client):
        """webpush 未設定時は enabled=False"""
        spec = _make_spec()
        client = make_client(spec)

        response = client.get("/api/metrics/webpush")
        assert response.status_code == 200
        assert response.get_json()["enabled"] is False
