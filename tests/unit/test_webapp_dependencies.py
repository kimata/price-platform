from __future__ import annotations

import flask
import pytest

import price_platform.webapp


def test_build_app_dependencies_returns_typed_container() -> None:
    services = price_platform.webapp.build_app_services(metrics_db="metrics")
    dependencies = price_platform.webapp.build_app_dependencies(
        config={"name": "app"},
        stores={"price_store": "store"},
        services=services,
    )

    assert dependencies.config == {"name": "app"}
    assert dependencies.stores == {"price_store": "store"}
    assert dependencies.services.metrics_db == "metrics"


def test_install_and_get_typed_dependencies() -> None:
    app = flask.Flask(__name__)
    services = price_platform.webapp.build_app_services(metrics_db="metrics")
    dependencies = price_platform.webapp.build_app_dependencies(
        config={"name": "app"},
        stores={"price_store": "store"},
        services=services,
    )
    price_platform.webapp.install_dependencies(app, "test.dependencies", dependencies)

    with app.app_context():
        loaded = price_platform.webapp.get_typed_dependencies(
            "test.dependencies",
            price_platform.webapp.AppDependencies,
        )

    assert loaded is dependencies


def test_get_dependencies_raises_when_missing() -> None:
    app = flask.Flask(__name__)

    with app.app_context(), pytest.raises(RuntimeError, match="Dependencies not installed"):
        price_platform.webapp.get_dependencies("missing")


def test_build_app_services_resolves_factory_lazily_per_request() -> None:
    app = flask.Flask(__name__)
    calls: list[str] = []
    services = price_platform.webapp.build_app_services(
        notification_store_factory=lambda: calls.append("notification") or "store"
    )

    with app.test_request_context():
        assert services.notification_store == "store"
        assert services.notification_store == "store"

    with app.test_request_context():
        assert services.notification_store == "store"

    assert calls == ["notification", "notification"]


def test_build_app_services_rejects_service_and_factory_together() -> None:
    with pytest.raises(ValueError, match="metrics_db and metrics_db_factory"):
        price_platform.webapp.build_app_services(
            metrics_db="metrics",
            metrics_db_factory=lambda: "other",
        )
