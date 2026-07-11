"""TwitterRateLimit のヘッダ解析テスト (B5 回帰)。"""

from __future__ import annotations

from price_platform.notification.twitter_poster import TwitterRateLimit
from price_platform.platform import clock

_FULL_HEADERS = {
    "x-app-limit-24hour-limit": "17",
    "x-app-limit-24hour-remaining": "0",
    "x-app-limit-24hour-reset": str(int(clock.now().timestamp()) + 3600),
    "x-user-limit-24hour-limit": "17",
    "x-user-limit-24hour-remaining": "0",
    "x-user-limit-24hour-reset": str(int(clock.now().timestamp()) + 3600),
}


def test_from_headers_parses_complete_headers() -> None:
    rate_limit = TwitterRateLimit.from_headers(_FULL_HEADERS)

    assert rate_limit is not None
    assert rate_limit.is_limited
    # リセットまで約 1 時間 + 60 秒マージン
    assert 3500 < rate_limit.wait_seconds < 3700


def test_from_headers_returns_none_when_headers_missing() -> None:
    """B5 回帰: 24 時間系ヘッダが無い 429 (15 分ウィンドウ) では None を返す.

    欠落を "0" で補うと epoch(1970) reset の偽状態になり、
    待機計算が 60 秒に潰れて 429 へ再突撃し続ける。
    """
    assert TwitterRateLimit.from_headers({}) is None
    assert TwitterRateLimit.from_headers({"x-rate-limit-remaining": "0"}) is None

    # 一部だけ欠けている場合も None
    partial = dict(_FULL_HEADERS)
    del partial["x-user-limit-24hour-reset"]
    assert TwitterRateLimit.from_headers(partial) is None


def test_from_headers_returns_none_on_invalid_values() -> None:
    broken = dict(_FULL_HEADERS)
    broken["x-app-limit-24hour-reset"] = "not-a-number"
    assert TwitterRateLimit.from_headers(broken) is None
