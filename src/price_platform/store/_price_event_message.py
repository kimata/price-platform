"""Shared fallback message helpers for price events."""

from __future__ import annotations

from typing import Any


def format_event_message(
    product_name: str,
    *,
    event_type_value: str,
    previous_price: int | None = None,
    reference_price: int | None = None,
    change_percent: float | None = None,
    period_days: int | None = None,
    rarity_tier: str | None = None,
) -> str:
    if event_type_value == "all_time_low":
        if previous_price is not None:
            return f"{product_name} が過去最安値を更新しました。前回の底値は {previous_price:,}円 です。"
        return f"{product_name} が過去最安値を更新しました。"

    if event_type_value == "statistical_low":
        body = _statistical_low_body(rarity_tier)
        return f"{product_name} が{body}"

    if event_type_value.startswith("period_low_"):
        days = period_days or _parse_period_days(event_type_value) or 30
        return f"{product_name} が直近{days}日で最も安い水準になりました。"

    if event_type_value == "price_drop":
        if previous_price is not None:
            return f"{product_name} が {previous_price:,}円 から値下がりしました。"
        return f"{product_name} が値下がりしました。"

    if event_type_value == "price_recovery":
        return f"{product_name} は安値圏から価格が戻りつつあります。"

    if event_type_value == "flea_bargain":
        if reference_price is not None:
            return f"{product_name} は相場 {reference_price:,}円 と比べても割安です。"
        return f"{product_name} は相場と比べても割安です。"

    if event_type_value == "good_used_deal":
        if reference_price is not None:
            return f"{product_name} の中古価格は新品参考 {reference_price:,}円 と比べて割安です。"
        return f"{product_name} の中古価格は割安です。"

    if change_percent is not None:
        return f"{product_name} に価格変動がありました ({change_percent:+.1f}%)。"
    return f"{product_name} に価格イベントが発生しました。"


def _statistical_low_body(rarity_tier: str | None) -> str:
    if rarity_tier == "EXTREME":
        return "過去の価格分布でもほとんど見ない安値水準です。"
    if rarity_tier == "VERY_HIGH":
        return "過去の価格分布と見比べてもかなり珍しい水準です。"
    if rarity_tier == "HIGH":
        return "過去の価格分布と見比べても珍しい水準です。"
    if rarity_tier == "MODERATE":
        return "相場より安めの水準です。"
    return "統計的に見て安値圏です。"


def _parse_period_days(event_type_value: str) -> int | None:
    try:
        return int(event_type_value.rsplit("_", 1)[-1])
    except ValueError:
        return None


def format_event_message_from_event(event: Any, product_name: str) -> str:
    event_type = getattr(getattr(event, "event_type", None), "value", None) or str(getattr(event, "event_type", ""))
    return format_event_message(
        product_name,
        event_type_value=event_type,
        previous_price=getattr(event, "previous_price", None),
        reference_price=getattr(event, "reference_price", None),
        change_percent=getattr(event, "change_percent", None),
        period_days=getattr(event, "period_days", None),
        rarity_tier=getattr(event, "rarity_tier", None),
    )

