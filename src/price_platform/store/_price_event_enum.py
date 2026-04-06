"""Shared price-event enum for cross-project convergence."""

from __future__ import annotations

from enum import StrEnum


class PriceEventType(StrEnum):
    ALL_TIME_LOW = "all_time_low"
    STATISTICAL_LOW = "statistical_low"
    FLEA_BARGAIN = "flea_bargain"
    PERIOD_LOW_365 = "period_low_365"
    PERIOD_LOW_180 = "period_low_180"
    PERIOD_LOW_90 = "period_low_90"
    PERIOD_LOW_60 = "period_low_60"
    PERIOD_LOW_30 = "period_low_30"
    PRICE_DROP = "price_drop"
    GOOD_USED_DEAL = "good_used_deal"
    PRICE_RECOVERY = "price_recovery"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def emoji(self) -> str:
        return _EMOJIS[self]

    @property
    def priority(self) -> int:
        return _PRIORITIES[self]


_LABELS = {
    PriceEventType.ALL_TIME_LOW: "過去最安値",
    PriceEventType.STATISTICAL_LOW: "統計的安値",
    PriceEventType.FLEA_BARGAIN: "フリマ割安",
    PriceEventType.PERIOD_LOW_365: "365日最安値",
    PriceEventType.PERIOD_LOW_180: "180日最安値",
    PriceEventType.PERIOD_LOW_90: "90日最安値",
    PriceEventType.PERIOD_LOW_60: "60日最安値",
    PriceEventType.PERIOD_LOW_30: "30日最安値",
    PriceEventType.PRICE_DROP: "値下がり",
    PriceEventType.GOOD_USED_DEAL: "中古割安",
    PriceEventType.PRICE_RECOVERY: "価格回復",
}

_EMOJIS = {
    PriceEventType.ALL_TIME_LOW: "🎯",
    PriceEventType.STATISTICAL_LOW: "📊",
    PriceEventType.FLEA_BARGAIN: "🛍️",
    PriceEventType.PERIOD_LOW_365: "📉",
    PriceEventType.PERIOD_LOW_180: "📉",
    PriceEventType.PERIOD_LOW_90: "📉",
    PriceEventType.PERIOD_LOW_60: "📉",
    PriceEventType.PERIOD_LOW_30: "📉",
    PriceEventType.PRICE_DROP: "📉",
    PriceEventType.GOOD_USED_DEAL: "♻️",
    PriceEventType.PRICE_RECOVERY: "📈",
}

_PRIORITIES = {
    PriceEventType.ALL_TIME_LOW: 1,
    PriceEventType.FLEA_BARGAIN: 2,
    PriceEventType.STATISTICAL_LOW: 3,
    PriceEventType.PERIOD_LOW_365: 4,
    PriceEventType.PERIOD_LOW_180: 5,
    PriceEventType.PERIOD_LOW_90: 6,
    PriceEventType.PERIOD_LOW_60: 7,
    PriceEventType.PERIOD_LOW_30: 8,
    PriceEventType.PRICE_DROP: 9,
    PriceEventType.GOOD_USED_DEAL: 10,
    PriceEventType.PRICE_RECOVERY: 11,
}

