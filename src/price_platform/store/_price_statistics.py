"""Statistical helpers for price event detection."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._price_event_types import PriceHistoryPoint, PriceRecordProtocol


@dataclass(frozen=True)
class DataQuality:
    sample_count: int
    distinct_observation_days: int
    coverage_ratio: float
    history_span_days: int

    @property
    def is_sufficient(self) -> bool:
        return self.distinct_observation_days > 0


def build_daily_price_points(
    history: Sequence[PriceRecordProtocol[Any]],
    *,
    mode: str = "median",
) -> list[PriceHistoryPoint]:
    """Compress raw observations into daily representative prices."""

    grouped: dict[date, list[PriceRecordProtocol[Any]]] = defaultdict(list)
    for record in sorted(history, key=lambda item: item.recorded_at):
        grouped[record.recorded_at.date()].append(record)

    points: list[PriceHistoryPoint] = []
    for records in grouped.values():
        prices = [record.price for record in records]
        representative = prices[-1] if mode == "last" else int(statistics.median(prices))
        points.append(PriceHistoryPoint(price=representative, recorded_at=records[-1].recorded_at))
    return points


def assess_data_quality(
    history: Sequence[PriceHistoryPoint],
    *,
    window_days: int,
) -> DataQuality:
    if not history:
        return DataQuality(
            sample_count=0,
            distinct_observation_days=0,
            coverage_ratio=0.0,
            history_span_days=0,
        )

    distinct_days = {point.recorded_at.date() for point in history}
    first_day = min(distinct_days)
    last_day = max(distinct_days)
    history_span_days = (last_day - first_day).days + 1
    effective_window = max(window_days, history_span_days, 1)
    return DataQuality(
        sample_count=len(history),
        distinct_observation_days=len(distinct_days),
        coverage_ratio=min(len(distinct_days) / effective_window, 1.0),
        history_span_days=history_span_days,
    )


def compute_percentile_rank(prices: Sequence[int], current_price: int) -> float:
    if not prices:
        return 50.0
    count_at_or_below = sum(1 for price in prices if price <= current_price)
    return count_at_or_below / len(prices) * 100


def wilson_upper_bound(successes: int, total: int, *, z_score: float) -> float:
    if total <= 0:
        return 1.0
    phat = successes / total
    denominator = 1 + z_score * z_score / total
    center = phat + z_score * z_score / (2 * total)
    margin = z_score * math.sqrt((phat * (1 - phat) + z_score * z_score / (4 * total)) / total)
    return min((center + margin) / denominator, 1.0)


def compute_robust_baseline(
    history: Sequence[PriceHistoryPoint],
    *,
    now: datetime,
    window_days: int,
    exclude_recent_days: int,
) -> int | None:
    cutoff_start = now - timedelta(days=window_days)
    cutoff_end = now - timedelta(days=exclude_recent_days)
    prices = [point.price for point in history if cutoff_start <= point.recorded_at <= cutoff_end]
    if len(prices) < 3:
        return None
    return int(statistics.median(prices))


def is_returning_from_spike(
    *,
    baseline: int,
    recent_prices: Sequence[int],
    current_price: int,
    spike_threshold_percent: float,
    baseline_band_percent: float,
) -> bool:
    if baseline <= 0:
        return False

    has_spike = any(
        (price - baseline) / baseline * 100 > spike_threshold_percent
        for price in recent_prices
    )
    is_near_baseline = abs(current_price - baseline) / baseline * 100 <= baseline_band_percent
    return has_spike and is_near_baseline

