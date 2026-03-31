from __future__ import annotations

import contextlib
from pathlib import Path

import flask

import price_platform.webapp


class _ConnectionStub:
    @contextlib.contextmanager
    def request_connection(self):
        yield object()


def test_create_configured_platform_app_runs_declared_steps() -> None:
    route_installed = {"value": False}
    warmup_called = {"value": False}

    main_blueprint = flask.Blueprint("main", __name__)

    @main_blueprint.route("/hello")
    def hello() -> str:
        return "hello"

    optional_blueprint = flask.Blueprint("optional", __name__)

    @optional_blueprint.route("/optional")
    def optional() -> str:
        return "optional"

    def install_extra_routes(app: flask.Flask) -> None:
        route_installed["value"] = True

        @app.route("/extra")
        def extra() -> str:
            return "extra"

    def warmup() -> None:
        warmup_called["value"] = True

    spec = price_platform.webapp.PlatformAppSpec(
        settings=price_platform.webapp.WebAppSettings(
            app_name="test-app",
            url_prefix="/test",
            external_url="https://example.com",
        ),
        common_routes=price_platform.webapp.CommonRoutesSettings(
            url_prefix="/test",
            img_dir=Path("/tmp/img"),
            flea_thumb_dir=Path("/tmp/thumb"),
        ),
        healthcheck=lambda: None,
        blueprints=(
            price_platform.webapp.BlueprintRegistration(main_blueprint, "/test/api"),
        ),
        optional_blueprints=(
            price_platform.webapp.OptionalBlueprintRegistration(
                loader=lambda: optional_blueprint,
                url_prefix="/test/api",
            ),
        ),
        route_installers=(install_extra_routes,),
        warmup=warmup,
    )

    app = price_platform.webapp.create_configured_platform_app(
        spec,
        connection_getter=lambda: _ConnectionStub(),
    )
    client = app.test_client()

    assert route_installed["value"] is True
    assert warmup_called["value"] is True
    assert client.get("/test/api/hello").status_code == 200
    assert client.get("/test/api/optional").status_code == 200
    assert client.get("/extra").status_code == 200


def test_register_optional_blueprints_skips_missing_import() -> None:
    app = flask.Flask(__name__)

    price_platform.webapp.register_optional_blueprints(
        app,
        (
            price_platform.webapp.OptionalBlueprintRegistration(
                loader=lambda: (_ for _ in ()).throw(ImportError("missing")),
            ),
        ),
    )

    assert len(app.blueprints) == 0


def test_install_seo_routes_registers_standard_responses() -> None:
    app = flask.Flask(__name__)

    price_platform.webapp.install_seo_routes(
        app,
        price_platform.webapp.SeoRoutesSpec(
            url_prefix="/test",
            sitemap_builder=lambda: "<xml>sitemap</xml>",
            robots_builder=lambda: "User-agent: *",
            image_sitemap_builder=lambda: "<xml>images</xml>",
        ),
    )

    client = app.test_client()

    sitemap = client.get("/test/sitemap.xml")
    assert sitemap.status_code == 200
    assert sitemap.headers["Content-Type"].startswith("application/xml")

    robots = client.get("/test/robots.txt")
    assert robots.status_code == 200
    assert robots.headers["Content-Type"].startswith("text/plain")

    images = client.get("/test/sitemap-images.xml")
    assert images.status_code == 200
    assert images.headers["Content-Type"].startswith("application/xml")


def test_create_warmup_runs_all_steps() -> None:
    steps: list[str] = []

    warmup = price_platform.webapp.create_warmup(
        lambda: steps.append("catalog"),
        lambda: steps.append("store"),
        lambda: steps.append("guide"),
    )

    warmup()

    assert steps == ["catalog", "store", "guide"]


def test_notify_content_update_emits_event(monkeypatch) -> None:
    captured: list[object] = []

    import my_lib.webapp.event

    monkeypatch.setattr(my_lib.webapp.event, "notify_event", lambda event_type: captured.append(event_type))

    price_platform.webapp.notify_content_update()

    assert captured == [my_lib.webapp.event.EVENT_TYPE.CONTENT]
