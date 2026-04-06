"""Rarity classification helpers for statistical price events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._price_event_types import PriceEventConfig
from ._price_statistics import DataQuality, wilson_upper_bound


class RarityTier(StrEnum):
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    EXTREME = "EXTREME"


@dataclass(frozen=True)
class RarityAssessment:
    percentile_rank: float
    conservative_percentile_upper_bound: float
    tier: RarityTier | None


def resolve_rarity(
    *,
    count_at_or_below: int,
    sample_count: int,
    data_quality: DataQuality,
    config: PriceEventConfig,
) -> RarityAssessment:
    if sample_count <= 0:
        return RarityAssessment(
            percentile_rank=50.0,
            conservative_percentile_upper_bound=100.0,
            tier=None,
        )

    percentile_rank = count_at_or_below / sample_count * 100
    upper_bound_percentile = (
        wilson_upper_bound(
            count_at_or_below,
            sample_count,
            z_score=config.rarity_confidence_z_score,
        )
        * 100
    )

    if data_quality.coverage_ratio < config.rarity_min_coverage_ratio:
        tier = None
    elif data_quality.distinct_observation_days >= 90 and upper_bound_percentile <= config.extreme_rarity_max_percentile:
        tier = RarityTier.EXTREME
    elif data_quality.distinct_observation_days >= 60 and upper_bound_percentile <= config.very_high_rarity_max_percentile:
        tier = RarityTier.VERY_HIGH
    elif data_quality.distinct_observation_days >= 30 and upper_bound_percentile <= config.high_rarity_max_percentile:
        tier = RarityTier.HIGH
    elif data_quality.distinct_observation_days >= 14 and upper_bound_percentile <= config.moderate_rarity_max_percentile:
        tier = RarityTier.MODERATE
    else:
        tier = None

    return RarityAssessment(
        percentile_rank=percentile_rank,
        conservative_percentile_upper_bound=upper_bound_percentile,
        tier=tier,
    )

