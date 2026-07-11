"""webapp/cors.py の同一オリジン判定テスト (B2 回帰)。"""

from __future__ import annotations

import pytest

import price_platform.webapp.cors as cors

ALLOWED = ["https://example.com"]


def test_exact_origin_match_is_allowed() -> None:
    assert cors.is_allowed_request_origin(
        allowed_origins=ALLOWED, origin="https://example.com", referer=None
    )


def test_spoofed_local_origin_is_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 回帰: Origin ヘッダ偽装 (localhost / プライベート IP) はデフォルトで拒否."""
    monkeypatch.delenv(cors.ALLOW_LOCAL_ORIGIN_ENV, raising=False)

    for spoofed in ("http://127.0.0.1", "http://localhost:3000", "http://192.168.1.10"):
        assert not cors.is_allowed_request_origin(
            allowed_origins=ALLOWED, origin=spoofed, referer=None
        ), f"{spoofed} が素通りしている"


def test_local_origin_allowed_when_env_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI / E2E 用のオプトインフラグで従来動作を再現できる."""
    monkeypatch.setenv(cors.ALLOW_LOCAL_ORIGIN_ENV, "1")

    assert cors.is_allowed_request_origin(
        allowed_origins=ALLOWED, origin="http://127.0.0.1", referer=None
    )


def test_local_origin_allowed_via_argument() -> None:
    assert cors.is_allowed_request_origin(
        allowed_origins=ALLOWED,
        origin="http://localhost:5173",
        referer=None,
        allow_local_origins=True,
    )


def test_referer_fallback_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cors.ALLOW_LOCAL_ORIGIN_ENV, raising=False)

    assert cors.is_allowed_request_origin(
        allowed_origins=ALLOWED, origin=None, referer="https://example.com/page"
    )
    assert not cors.is_allowed_request_origin(
        allowed_origins=ALLOWED, origin=None, referer="https://evil.example/page"
    )


def test_unlisted_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cors.ALLOW_LOCAL_ORIGIN_ENV, raising=False)

    assert not cors.is_allowed_request_origin(
        allowed_origins=ALLOWED, origin="https://evil.example", referer=None
    )
