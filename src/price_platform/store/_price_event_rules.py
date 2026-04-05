"""Rule helpers for price event detection."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ._price_event_types import PriceContext, PriceEventConfig, PriceEventDraft, PriceRecordT, SoldRecordT

logger = logging.getLogger(__name__)


def build_event_draft(
    record: PriceRecordT,
    *,
    event_type: Any,
    product_id: str,
    recorded_at: datetime,
    extra_fields: dict[str, object | None],
    previous_price: int | None = None,
    reference_price: int | None = None,
    change_percent: float | None = None,
    period_days: int | None = None,
) -> PriceEventDraft:
    return PriceEventDraft(
        event_type=event_type,
        product_id=product_id,
        store=record.store,
        price=record.price,
        url=record.url,
        recorded_at=recorded_at,
        previous_price=previous_price,
        reference_price=reference_price,
        change_percent=change_percent,
        period_days=period_days,
        extra_fields=extra_fields,
    )


def check_all_time_low(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    lowest = ctx.all_time_lowest_new
    if lowest is None or current.price >= lowest.price:
        return None
    logger.info("[ALL_TIME_LOW] %s: %s円 < %s円", ctx.product_id, f"{current.price:,}", f"{lowest.price:,}")
    return build_event_draft(
        current,
        event_type=event_types.ALL_TIME_LOW,
        product_id=ctx.product_id,
        previous_price=lowest.price,
        recorded_at=now,
        extra_fields=extra_fields,
    )


def check_period_low(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    period_event_map: dict[int, Any],
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    for days in sorted(config.period_low_days, reverse=True):
        lowest = ctx.period_lowest.get(days)
        if lowest is None or current.price >= lowest.price:
            continue
        event_type = period_event_map.get(days)
        if event_type is None:
            continue

        history = ctx.price_history.get(days, [])
        new_history = [p for p in history if not p.is_used]
        avg_price = None
        change_percent = None
        if new_history:
            avg_price = int(sum(p.price for p in new_history) / len(new_history))
            if avg_price > 0:
                change_percent = (current.price - avg_price) / avg_price * 100

        logger.info("[PERIOD_LOW_%s] %s: %s円 < %s円", days, ctx.product_id, f"{current.price:,}", f"{lowest.price:,}")
        return build_event_draft(
            current,
            event_type=event_type,
            product_id=ctx.product_id,
            previous_price=lowest.price,
            reference_price=avg_price,
            change_percent=change_percent,
            period_days=days,
            recorded_at=now,
            extra_fields=extra_fields,
        )
    return None


def check_price_drop(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    history = ctx.price_history.get(7, [])
    new_history = [p for p in history if not p.is_used]
    if len(new_history) < 2:
        return None
    recent_avg = sum(p.price for p in new_history) / len(new_history)
    if recent_avg <= 0:
        return None
    drop_percent = (recent_avg - current.price) / recent_avg * 100
    if drop_percent < config.price_drop_threshold_percent:
        return None
    logger.info(
        "[PRICE_DROP] %s: %.1f%%下落 (%s円 → %s円)",
        ctx.product_id,
        drop_percent,
        f"{recent_avg:,.0f}",
        f"{current.price:,}",
    )
    return build_event_draft(
        current,
        event_type=event_types.PRICE_DROP,
        product_id=ctx.product_id,
        previous_price=int(recent_avg),
        change_percent=-drop_percent,
        recorded_at=now,
        extra_fields=extra_fields,
    )


def check_good_used_deal(
    product_id: str,
    used: PriceRecordT,
    new_price: int,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    if new_price <= 0:
        return None
    ratio = used.price / new_price
    if ratio > config.good_used_ratio_max:
        return None
    logger.info("[GOOD_USED_DEAL] %s: 中古%s円 / 新品%s円 = %.1f%%", product_id, f"{used.price:,}", f"{new_price:,}", ratio * 100)
    return build_event_draft(
        used,
        event_type=event_types.GOOD_USED_DEAL,
        product_id=product_id,
        reference_price=new_price,
        change_percent=ratio * 100,
        recorded_at=now,
        extra_fields=extra_fields,
    )


def check_flea_bargain(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    if len(ctx.sold_records) < 3:
        return None
    prices = sorted(record.price for record in ctx.sold_records)
    median_price = prices[len(prices) // 2]
    if median_price <= 0:
        return None
    discount_percent = (median_price - current.price) / median_price * 100
    if discount_percent < config.flea_bargain_threshold_percent:
        return None
    logger.info(
        "[FLEA_BARGAIN] %s: %s円 vs 相場%s円 (%.1f%%安)",
        ctx.product_id,
        f"{current.price:,}",
        f"{median_price:,}",
        discount_percent,
    )
    return build_event_draft(
        current,
        event_type=event_types.FLEA_BARGAIN,
        product_id=ctx.product_id,
        reference_price=median_price,
        change_percent=-discount_percent,
        recorded_at=now,
        extra_fields=extra_fields,
    )


def check_price_recovery(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    history = ctx.price_history.get(30, [])
    new_history = [p for p in history if not p.is_used]
    if len(new_history) < 5:
        return None

    lowest = min(new_history, key=lambda p: p.price)
    lowest_index = new_history.index(lowest)
    days_since_low = (now - lowest.recorded_at).days
    if days_since_low < config.price_recovery_min_days_after_low:
        return None

    prices_after_low = new_history[lowest_index + 1 :]
    if len(prices_after_low) < config.price_recovery_consecutive_rises:
        return None

    consecutive_rises = 0
    prev_price = lowest.price
    for price in prices_after_low:
        if price.price > prev_price:
            consecutive_rises += 1
        else:
            consecutive_rises = 0
        prev_price = price.price

    recovery_percent = (current.price - lowest.price) / lowest.price * 100
    is_bottom_rebound = recovery_percent >= config.price_recovery_threshold_percent
    is_consecutive_rise = (
        consecutive_rises >= config.price_recovery_consecutive_rises
        and recovery_percent >= config.price_recovery_consecutive_min_percent
    )
    if not (is_bottom_rebound or is_consecutive_rise):
        return None
    logger.info(
        "[PRICE_RECOVERY] %s: %s円 → %s円 (+%.1f%%, %s回連続上昇)",
        ctx.product_id,
        f"{lowest.price:,}",
        f"{current.price:,}",
        recovery_percent,
        consecutive_rises,
    )
    return build_event_draft(
        current,
        event_type=event_types.PRICE_RECOVERY,
        product_id=ctx.product_id,
        previous_price=lowest.price,
        change_percent=recovery_percent,
        recorded_at=now,
        extra_fields=extra_fields,
    )
