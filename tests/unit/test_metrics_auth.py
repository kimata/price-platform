from __future__ import annotations

from pathlib import Path

import flask

import price_platform.auth.metrics_auth


def _make_settings(secret_path: Path) -> price_platform.auth.metrics_auth.MetricsAuthSettings:
    return price_platform.auth.metrics_auth.MetricsAuthSettings(
        enabled=True,
        password_hash="",
        jwt_secret_path=secret_path,
        jwt_expiry_hours=1,
    )


def test_issue_and_verify_auth_token(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path / "jwt.key")

    token = price_platform.auth.metrics_auth.issue_auth_token(settings)
    payload = price_platform.auth.metrics_auth.verify_auth_token(token, settings)

    assert payload is not None
    assert payload["sub"] == "user"


def test_verify_auth_token_returns_none_when_secret_missing(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path / "missing.key")

    assert price_platform.auth.metrics_auth.verify_auth_token("token", settings) is None


def test_require_auth_skips_when_disabled() -> None:
    settings = price_platform.auth.metrics_auth.MetricsAuthSettings(enabled=False)
    app = flask.Flask(__name__)

    @price_platform.auth.metrics_auth.require_auth(lambda: settings)
    def protected() -> tuple[str, int]:
        return "ok", 200

    with app.test_request_context("/"):
        assert protected() == ("ok", 200)


def test_metrics_auth_blueprint_login_requires_configured_password(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path / "jwt.key")
    app = flask.Flask(__name__)
    app.register_blueprint(
        price_platform.auth.metrics_auth.create_metrics_auth_blueprint(
            settings_getter=lambda: settings,
        ),
        url_prefix="/auth",
    )

    response = app.test_client().post("/auth/login", json={"password": "secret"})

    assert response.status_code == 500
    assert response.get_json()["code"] == "NOT_CONFIGURED"
