from __future__ import annotations

from datetime import datetime

from price_platform.social_posts import (
    SocialCopyMetadata,
    SocialPostContext,
    _tweet_length,
    append_tracking_params,
    compose_social_post,
)


def test_append_tracking_params_preserves_path() -> None:
    tracked = append_tracking_params(
        "https://example.com/detail/foo",
        post_variant="hook",
        post_id="abc123",
        event_type="price_drop",
    )

    assert tracked.startswith("https://example.com/detail/foo?")
    assert "post_variant=hook" in tracked
    assert "post_id=abc123" in tracked
    assert "utm_source=x" in tracked


def test_tweet_length_counts_url_as_tco() -> None:
    text = "Hello https://example.com/very/long/path?foo=bar&baz=qux world"
    length = _tweet_length(text)
    # "Hello " (6) + 23 (t.co) + " world" (6) = 35
    assert length == 35


def test_compose_social_post_retains_social_copy_with_long_url() -> None:
    """social.yaml の hooks/trust_points が長い URL でも削除されないことを検証する。"""
    hook = "通勤や移動時間を快適にしたい人には相性の良い定番です。"
    trust = "ノイキャン重視で比較している人には見やすい動きです。"

    post = compose_social_post(
        SocialPostContext(
            product_id="sony-wh-1000xm6",
            product_line="SONY WH-1000XM6",
            detail_url="https://example.com/detail/sony-wh-1000xm6/black",
            event_type_value="price_drop",
            event_type_label="大幅値下げ",
            event_emoji="📉",
            store_label="Amazon",
            price=49800,
            previous_price=54800,
            recorded_at=datetime(2026, 4, 4, 12, 0, 0),
            hashtag="#Sony #WH1000XM6",
            social_copy=SocialCopyMetadata(
                hooks=(hook,),
                trust_points=(trust,),
            ),
        )
    )

    # hooks か trust_points のいずれかが投稿文に含まれていること
    assert hook in post.message or trust in post.message


def test_compose_social_post_prefers_humanized_copy() -> None:
    post = compose_social_post(
        SocialPostContext(
            product_id="sony-wh-1000xm6",
            product_line="SONY WH-1000XM6 ブラック",
            detail_url="https://example.com/detail/sony-wh-1000xm6/black",
            event_type_value="price_drop",
            event_type_label="大幅値下げ",
            event_emoji="📉",
            store_label="Amazon",
            price=49800,
            previous_price=54800,
            recorded_at=datetime(2026, 4, 4, 12, 0, 0),
            hashtag="#Sony #WH1000XM6",
            social_copy=SocialCopyMetadata(
                hooks=("通勤や移動時間を快適にしたい人には相性の良い定番です。",),
                trust_points=("ノイキャン重視で比較している人には見やすい動きです。",),
            ),
        )
    )

    assert "SONY WH-1000XM6 ブラック" in post.message
    assert "Amazonで 49,800円" in post.message
    assert "post_variant=" in post.message
    assert post.post_variant in {"fact", "hook", "trust"}
