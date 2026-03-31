from __future__ import annotations

import flask
import pytest

import price_platform.webapp


def test_build_app_dependencies_returns_typed_container() -> None:
    dependencies = price_platform.webapp.build_app_dependencies(
        config={"name": "app"},
        stores={"price_store": "store"},
    )

    assert dependencies.config == {"name": "app"}
    assert dependencies.stores == {"price_store": "store"}


def test_install_and_get_typed_dependencies() -> None:
    app = flask.Flask(__name__)
    dependencies = price_platform.webapp.build_app_dependencies(
        config={"name": "app"},
        stores={"price_store": "store"},
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
