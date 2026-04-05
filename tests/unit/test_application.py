from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import flask

import price_platform.application


class _ConnectionStub:
    @contextlib.contextmanager
    def request_connection(self):
        yield object()


def test_build_optional_service_factory_respects_enabled_flag(tmp_path: Path) -> None:
    opened: list[Path] = []

    factory = price_platform.application.build_optional_service_factory(
        enabled=lambda config: config.enabled,
        path_getter=lambda config: config.path,
        opener=lambda path: opened.append(path) or path.name,
    )

    assert factory(SimpleNamespace(enabled=False, path=tmp_path / "disabled.db")) is None
    assert factory(SimpleNamespace(enabled=True, path=tmp_path / "enabled.db")) == "enabled.db"
    assert opened == [tmp_path / "enabled.db"]


def test_safe_service_getter_returns_none_for_uninitialized_runtime() -> None:
    getter = price_platform.application.safe_service_getter(
        lambda: (_ for _ in ()).throw(RuntimeError("not initialized"))
    )

    assert getter() is None


def test_create_standard_webapi_app_builds_and_installs_dependencies(tmp_path: Path) -> None:
    api_blueprint = flask.Blueprint("api", __name__)

    @api_blueprint.route("/ping")
    def ping() -> str:
        return "pong"

    config = SimpleNamespace(
        webapp=SimpleNamespace(external_url="https://example.com"),
        absolute_cache_path=tmp_path / "cache",
    )
    dependencies = price_platform.webapp.AppDependencies(
        config=config,
        stores=SimpleNamespace(price_store=SimpleNamespace(get_last_update_time=lambda: "ok")),
        services=SimpleNamespace(),
    )
    installed: list[object] = []

    app = price_platform.application.create_standard_webapi_app(
        config,
        definition=price_platform.application.StandardWebApiAppDefinition(
            app_name="test-app",
            url_prefix="/test",
            base_dir=tmp_path,
            blueprints=(price_platform.webapp.BlueprintRegistration(api_blueprint, "/test/api"),),
        ),
        dependencies=dependencies,
        connection_getter=lambda: _ConnectionStub(),
        install_dependencies=lambda app, deps: installed.append((app, deps)),
    )

    client = app.test_client()

    assert client.get("/test/api/ping").status_code == 200
    assert client.get("/test/api/healthz").status_code == 200
    assert installed == [(app, dependencies)]
