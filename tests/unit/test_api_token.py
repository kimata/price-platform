from __future__ import annotations

from pathlib import Path

import flask

import price_platform.auth.api_token
import price_platform.auth.metrics_auth


def test_generate_and_verify_api_token_uses_path_secret(tmp_path: Path) -> None:
    secret_path = tmp_path / "api_token_secret.key"
    settings = price_platform.auth.api_token.ApiTokenSettings(
        secret_path=secret_path,
        expiry_sec=300,
        allowed_origins=("https://example.com",),
    )

    token = price_platform.auth.api_token.generate_api_token(settings)

    assert secret_path.exists()
    payload = price_platform.auth.api_token.verify_api_token(token, settings)
    assert payload is not None
    assert payload["type"] == "api"


def test_api_token_blueprint_rejects_cross_origin_request(tmp_path: Path) -> None:
    app = flask.Flask(__name__)
    settings = price_platform.auth.api_token.ApiTokenSettings(
        secret_path=tmp_path / "api_token_secret.key",
        allowed_origins=("https://example.com",),
    )
    app.register_blueprint(
        price_platform.auth.api_token.create_api_token_blueprint(settings_getter=lambda: settings),
        url_prefix="/api",
    )

    client = app.test_client()
    response = client.get("/api/token", headers={"Origin": "https://invalid.example.com"})

    assert response.status_code == 403


def test_build_api_token_facade_binds_config_getter(tmp_path: Path) -> None:
    class WebappConfigStub:
        external_url = "https://example.com"

    class ConfigStub:
        webapp = WebappConfigStub()

    facade = price_platform.auth.api_token.build_api_token_facade(
        config_getter=lambda: ConfigStub(),
        secret_path=tmp_path / "api_token_secret.key",
    )

    token = facade.generate_api_token()
    payload = facade.verify_api_token(token)

    assert payload is not None
    assert payload["type"] == "api"


def test_build_metrics_auth_facade_binds_config_getter(tmp_path: Path) -> None:
    class AuthConfigStub:
        enabled = True
        password_hash = "hash"
        jwt_secret_path = tmp_path / "jwt_secret.key"
        jwt_expiry_hours = 12

    class MetricsConfigStub:
        auth = AuthConfigStub()

    class ConfigStub:
        metrics = MetricsConfigStub()

    facade = price_platform.auth.metrics_auth.build_metrics_auth_facade(
        config_getter=lambda: ConfigStub(),
    )

    settings = facade.settings_getter()

    assert settings.enabled is True
    assert settings.jwt_secret_path == tmp_path / "jwt_secret.key"
