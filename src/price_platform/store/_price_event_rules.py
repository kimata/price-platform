"""Rule helpers for price event detection."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ._price_event_rarity import resolve_rarity
from ._price_event_types import (
    PriceContext,
    PriceEventConfig,
    PriceEventDraft,
    PriceRecordProtocol,
    PriceRecordT,
    SoldRecordT,
)
from ._price_statistics import (
    assess_data_quality,
    compute_percentile_rank,
    compute_robust_baseline,
    is_returning_from_spike,
)

logger = logging.getLogger(__name__)


def build_event_draft(
    record: PriceRecordProtocol[Any],
    *,
    event_type: Any,
    product_id: str,
    recorded_at: datetime,
    extra_fields: dict[str, object | None],
    previous_price: int | None = None,
    reference_price: int | None = None,
    change_percent: float | None = None,
    period_days: int | None = None,
    percentile_rank: float | None = None,
    rarity_tier: str | None = None,
    baseline_price: int | None = None,
    sample_days: int | None = None,
    sample_count: int | None = None,
    rarity_window_days: int | None = None,
    detector_version: str | None = None,
    canonical_variant_key: str | None = None,
    event_family: str | None = None,
    comparison_basis: str | None = None,
    severity: str | None = None,
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
        percentile_rank=percentile_rank,
        rarity_tier=rarity_tier,
        baseline_price=baseline_price,
        sample_days=sample_days,
        sample_count=sample_count,
        rarity_window_days=rarity_window_days,
        detector_version=detector_version,
        canonical_variant_key=canonical_variant_key,
        event_family=event_family,
        comparison_basis=comparison_basis,
        severity=severity,
        extra_fields=extra_fields,
    )


def check_all_time_low(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    lowest = ctx.all_time_lowest_new
    if lowest is None or current.price >= lowest.price:
        return None
    quality = assess_data_quality(ctx.stable_full_new_price_history, window_days=max(365, config.all_time_low_min_days))
    if quality.distinct_observation_days < config.all_time_low_min_days:
        return None
    logger.info("[ALL_TIME_LOW] %s: %s円 < %s円", ctx.product_id, f"{current.price:,}", f"{lowest.price:,}")
    return build_event_draft(
        current,
        event_type=event_types.ALL_TIME_LOW,
        product_id=ctx.product_id,
        previous_price=lowest.price,
        recorded_at=now,
        sample_days=quality.distinct_observation_days,
        sample_count=quality.sample_count,
        detector_version=config.detector_version,
        canonical_variant_key=ctx.canonical_variant_key,
        event_family="all_time_low",
        comparison_basis="all_time",
        severity="major" if current.price <= int(lowest.price * 0.9) else "minor",
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
            sample_days=len(ctx.stable_price_history.get(days, [])),
            sample_count=len(ctx.stable_price_history.get(days, [])),
            rarity_window_days=days,
            detector_version=config.detector_version,
            canonical_variant_key=ctx.canonical_variant_key,
            event_family="period_low",
            comparison_basis="recent_market",
            severity="major" if days >= 180 else "minor",
            extra_fields=extra_fields,
        )
    return None


def check_statistical_low(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    event_type = getattr(event_types, "STATISTICAL_LOW", None)
    if event_type is None:
        return None

    stable_history = ctx.stable_price_history.get(config.rarity_window_days, [])
    quality = assess_data_quality(stable_history, window_days=config.rarity_window_days)
    if not quality.is_sufficient:
        return None

    prices = [point.price for point in stable_history]
    percentile_rank = compute_percentile_rank(prices, current.price)
    count_at_or_below = sum(1 for price in prices if price <= current.price)
    rarity = resolve_rarity(
        count_at_or_below=count_at_or_below,
        sample_count=len(prices),
        data_quality=quality,
        config=config,
    )
    if rarity.tier is None:
        return None

    logger.info(
        "[STATISTICAL_LOW] %s: %s円 percentile=%.1f tier=%s",
        ctx.product_id,
        f"{current.price:,}",
        percentile_rank,
        rarity.tier.value,
    )
    return build_event_draft(
        current,
        event_type=event_type,
        product_id=ctx.product_id,
        recorded_at=now,
        percentile_rank=percentile_rank,
        rarity_tier=rarity.tier.value,
        sample_days=quality.distinct_observation_days,
        sample_count=quality.sample_count,
        rarity_window_days=config.rarity_window_days,
        detector_version=config.detector_version,
        canonical_variant_key=ctx.canonical_variant_key,
        event_family="statistical_low",
        comparison_basis="historical_distribution",
        severity=rarity.tier.value.lower(),
        extra_fields=extra_fields,
    )


def check_price_drop(
    ctx: PriceContext[PriceRecordT, SoldRecordT],
    current: PriceRecordT,
    now: datetime,
    *,
    event_types: Any,
    config: PriceEventConfig,
    extra_fields: dict[str, object | None],
) -> PriceEventDraft | None:
    stable_history = ctx.stable_price_history.get(config.price_drop_baseline_window_days, [])
    if not stable_history:
        return None
    baseline = compute_robust_baseline(
        stable_history,
        now=now,
        window_days=config.price_drop_baseline_window_days,
        exclude_recent_days=config.price_drop_exclude_recent_days,
    )
    if baseline is None or baseline <= 0:
        return None

    recent_history = [
        record
        for record in ctx.full_new_price_history
        if record.recorded_at >= now - timedelta(days=config.price_drop_support_window_days)
    ]
    recent_prices = [record.price for record in recent_history]
    if is_returning_from_spike(
        baseline=baseline,
        recent_prices=recent_prices,
        current_price=current.price,
        spike_threshold_percent=config.price_drop_spike_threshold_percent,
        baseline_band_percent=config.price_drop_baseline_band_percent,
    ):
        return None

    drop_percent = (baseline - current.price) / baseline * 100
    if drop_percent < config.price_drop_threshold_percent:
        return None

    support_observations = sum(
        1
        for price in [*recent_prices, current.price]
        if price <= baseline * (1 - config.price_drop_threshold_percent / 100)
    )
    if (
        support_observations < config.price_drop_support_min_observations
        and drop_percent < config.price_drop_large_threshold_percent
    ):
        return None

    logger.info(
        "[PRICE_DROP] %s: %.1f%%下落 (%s円 → %s円)",
        ctx.product_id,
        drop_percent,
        f"{baseline:,.0f}",
        f"{current.price:,}",
    )
    return build_event_draft(
        current,
        event_type=event_types.PRICE_DROP,
        product_id=ctx.product_id,
        previous_price=int(baseline),
        change_percent=-drop_percent,
        recorded_at=now,
        baseline_price=baseline,
        sample_days=len(stable_history),
        sample_count=len(stable_history),
        rarity_window_days=config.price_drop_baseline_window_days,
        detector_version=config.detector_version,
        canonical_variant_key=ctx.canonical_variant_key,
        event_family="price_drop",
        comparison_basis="baseline_shift",
        severity="major" if drop_percent >= config.price_drop_large_threshold_percent else "minor",
        extra_fields=extra_fields,
    )


def check_good_used_deal(
    product_id: str,
    used: PriceRecordProtocol[Any],
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
        detector_version=config.detector_version,
        event_family="good_used_deal",
        comparison_basis="recent_market",
        severity="moderate",
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
        detector_version=config.detector_version,
        canonical_variant_key=ctx.canonical_variant_key,
        event_family="flea_bargain",
        comparison_basis="recent_market",
        severity="major" if discount_percent >= config.flea_bargain_threshold_percent * 1.5 else "moderate",
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
    history = ctx.stable_price_history.get(config.price_recovery_window_days, [])
    if len(history) < 5:
        return None

    lowest = min(history, key=lambda p: p.price)
    days_since_low = (now.date() - lowest.recorded_at.date()).days
    if days_since_low < config.price_recovery_min_days_after_low:
        return None

    prices_after_low = [point for point in history if point.recorded_at.date() > lowest.recorded_at.date()]
    if len(prices_after_low) < config.price_recovery_consecutive_rises:
        return None

    recovery_percent = (current.price - lowest.price) / lowest.price * 100
    recovered_days = sum(
        1
        for point in prices_after_low
        if point.price >= lowest.price * (1 + config.price_recovery_consecutive_min_percent / 100)
    )
    is_bottom_rebound = recovery_percent >= config.price_recovery_threshold_percent
    is_sustained_recovery = (
        recovered_days >= config.price_recovery_consecutive_rises
        and recovery_percent >= config.price_recovery_consecutive_min_percent
    )
    if not (is_bottom_rebound and is_sustained_recovery):
        return None
    logger.info(
        "[PRICE_RECOVERY] %s: %s円 → %s円 (+%.1f%%, %s日維持)",
        ctx.product_id,
        f"{lowest.price:,}",
        f"{current.price:,}",
        recovery_percent,
        recovered_days,
    )
    return build_event_draft(
        current,
        event_type=event_types.PRICE_RECOVERY,
        product_id=ctx.product_id,
        previous_price=lowest.price,
        change_percent=recovery_percent,
        recorded_at=now,
        sample_days=len(history),
        sample_count=len(history),
        rarity_window_days=config.price_recovery_window_days,
        detector_version=config.detector_version,
        canonical_variant_key=ctx.canonical_variant_key,
        event_family="price_recovery",
        comparison_basis="baseline_shift",
        severity="moderate",
        extra_fields=extra_fields,
    )
