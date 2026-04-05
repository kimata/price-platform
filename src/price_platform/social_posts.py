"""Shared helpers for humanized social post composition."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")
_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")

# Twitter/X replaces every URL with a t.co short link of this fixed length.
_TCO_URL_LENGTH = 23


@dataclass(frozen=True)
class SocialCopyMetadata:
    """Short, reusable product copy for social posts."""

    hooks: tuple[str, ...] = ()
    trust_points: tuple[str, ...] = ()
    summary: str | None = None
    review_snippet: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> SocialCopyMetadata:
        def _collect_list(key: str) -> tuple[str, ...]:
            value = data.get(key)
            if not isinstance(value, list):
                return ()
            return tuple(
                cleaned
                for item in value
                if isinstance(item, str) and (cleaned := _clean_copy_line(item))
            )

        summary = data.get("summary")
        review_snippet = data.get("review_snippet")
        return cls(
            hooks=_collect_list("hooks"),
            trust_points=_collect_list("trust_points"),
            summary=_clean_copy_line(summary) if isinstance(summary, str) else None,
            review_snippet=_clean_copy_line(review_snippet) if isinstance(review_snippet, str) else None,
        )


@dataclass(frozen=True)
class SocialPostContext:
    """Normalized input for composing a social post."""

    product_id: str
    product_line: str
    detail_url: str
    event_type_value: str
    event_type_label: str
    event_emoji: str
    store_label: str
    price: int
    recorded_at: datetime
    previous_price: int | None = None
    reference_price: int | None = None
    change_percent: float | None = None
    period_days: int | None = None
    hashtag: str | None = None
    social_copy: SocialCopyMetadata = SocialCopyMetadata()


@dataclass(frozen=True)
class ComposedSocialPost:
    """Composed post plus attribution metadata."""

    message: str
    tracked_url: str
    post_variant: str
    post_id: str


def _tweet_length(text: str) -> int:
    """Estimate the length of *text* as Twitter/X would count it.

    Every ``https?://`` URL is replaced by a t.co short link whose
    display length is fixed at :data:`_TCO_URL_LENGTH` characters,
    regardless of the original URL length.
    """
    shortened = _URL_RE.sub("x" * _TCO_URL_LENGTH, text)
    return len(shortened)


def _stable_index(seed: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % size


def _clean_copy_line(text: str | None, *, max_len: int = 64) -> str | None:
    if not text:
        return None
    compact = _WHITESPACE_RE.sub(" ", text).strip()
    if not compact:
        return None

    # 最初の文を句読点ごと取り出す（split すると句読点が消えるため search を使う）
    m = _SENTENCE_SPLIT_RE.search(compact)
    first_sentence = compact[: m.end()].strip() if m else compact
    if len(first_sentence) <= max_len:
        return first_sentence
    return f"{first_sentence[: max_len - 1].rstrip()}…"


def _select_human_line(ctx: SocialPostContext) -> str | None:
    candidates = list(ctx.social_copy.hooks)
    for fallback in (ctx.social_copy.summary, ctx.social_copy.review_snippet):
        cleaned = _clean_copy_line(fallback)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    if not candidates:
        return None
    idx = _stable_index(f"{ctx.product_id}:{ctx.event_type_value}:hook", len(candidates))
    return candidates[idx]


def _default_trust_lines(ctx: SocialPostContext) -> list[str]:
    if ctx.event_type_value == "all_time_low":
        return ["価格推移を追っている人には判断しやすい更新です。"]
    if ctx.event_type_value == "price_drop":
        return ["以前の価格と比べて目立った値下がりです。"]
    if ctx.event_type_value == "good_used_deal":
        return ["新品との価格差を見ながら判断しやすい動きです。"]
    if ctx.event_type_value == "flea_bargain":
        return ["相場と見比べてから判断したい人向けの出物です。"]
    return ["まずは価格推移だけ見ておくのもありです。"]


def _select_trust_line(ctx: SocialPostContext) -> str | None:
    candidates = list(ctx.social_copy.trust_points)
    for fallback in _default_trust_lines(ctx):
        cleaned = _clean_copy_line(fallback)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    if not candidates:
        return None
    idx = _stable_index(f"{ctx.product_id}:{ctx.event_type_value}:trust", len(candidates))
    return candidates[idx]


def _build_headline(ctx: SocialPostContext) -> str:
    if ctx.event_type_value == "all_time_low":
        body = "いまかなり注目の価格です。"
    elif ctx.event_type_value == "flea_bargain":
        body = "相場より低めの出物です。"
    elif ctx.event_type_value.startswith("period_low_"):
        period = ctx.period_days or 30
        body = f"ここ{period}日でいちばん低い水準です。"
    elif ctx.event_type_value == "price_drop":
        body = "価格がひと段階下がりました。"
    elif ctx.event_type_value == "good_used_deal":
        body = "中古を探している人には注目の水準です。"
    elif ctx.event_type_value == "price_recovery":
        body = "価格が戻り始めています。"
    else:
        body = ctx.event_type_label
    return f"{ctx.event_emoji} {body}"


def _build_fact_line(ctx: SocialPostContext) -> str:
    price_str = f"{ctx.price:,}円"
    base = f"{ctx.store_label}で {price_str}"

    if ctx.event_type_value == "all_time_low" and ctx.previous_price:
        return f"{base}。これまでの底値 {ctx.previous_price:,}円 を更新。"
    if ctx.event_type_value == "price_drop" and ctx.previous_price:
        return f"{base}。前回 {ctx.previous_price:,}円 から下がっています。"
    if ctx.event_type_value.startswith("period_low_") and ctx.reference_price and ctx.change_percent is not None:
        return f"{base}。期間平均 {ctx.reference_price:,}円 より {abs(ctx.change_percent):.0f}%低めです。"
    if ctx.event_type_value == "good_used_deal" and ctx.reference_price:
        ratio = int(ctx.price / ctx.reference_price * 100)
        return f"{base}。新品参考 {ctx.reference_price:,}円 に対して約{ratio}%です。"
    if ctx.event_type_value == "flea_bargain" and ctx.reference_price:
        diff = ctx.reference_price - ctx.price
        return f"{base}。相場 {ctx.reference_price:,}円 より {diff:,}円 低めです。"
    return base


def _build_post_id(ctx: SocialPostContext) -> str:
    seed = f"{ctx.product_id}:{ctx.event_type_value}:{ctx.recorded_at.isoformat()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def append_tracking_params(url: str, *, post_variant: str, post_id: str, event_type: str) -> str:
    """Append stable attribution parameters to social post URLs."""
    split = urlsplit(url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update(
        {
            "src": "x",
            "utm_source": "x",
            "utm_medium": "social",
            "utm_campaign": "price_alert",
            "utm_content": post_variant,
            "post_variant": post_variant,
            "post_id": post_id,
            "social_event": event_type,
        }
    )
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def compose_social_post(ctx: SocialPostContext) -> ComposedSocialPost:
    """Compose a humanized social post with stable attribution metadata."""
    human_line = _select_human_line(ctx)
    trust_line = _select_trust_line(ctx)
    fact_line = _build_fact_line(ctx)

    available_variants = ["fact"]
    if human_line:
        available_variants.append("hook")
    if trust_line:
        available_variants.append("trust")
    variant = available_variants[_stable_index(f"{ctx.product_id}:{ctx.event_type_value}:variant", len(available_variants))]

    post_id = _build_post_id(ctx)
    tracked_url = append_tracking_params(
        ctx.detail_url,
        post_variant=variant,
        post_id=post_id,
        event_type=ctx.event_type_value,
    )

    lines = [_build_headline(ctx), ctx.product_line]
    if variant == "hook" and human_line:
        lines.append(human_line)
    lines.append(fact_line)
    if variant == "trust" and trust_line:
        lines.append(trust_line)
    if variant == "fact" and human_line:
        lines.append(human_line)
    if ctx.hashtag:
        lines.append(ctx.hashtag)
    lines.append(tracked_url)

    while _tweet_length("\n".join(lines)) > 280 and len(lines) > 4:
        if ctx.hashtag in lines:
            lines.remove(ctx.hashtag)
            continue
        if trust_line and trust_line in lines:
            lines.remove(trust_line)
            continue
        if human_line and human_line in lines:
            lines.remove(human_line)
            continue
        break

    return ComposedSocialPost(
        message="\n".join(lines),
        tracked_url=tracked_url,
        post_variant=variant,
        post_id=post_id,
    )
