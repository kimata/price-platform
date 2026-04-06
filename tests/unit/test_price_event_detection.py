from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Never

from price_platform.store._price_event_rules import (
    check_price_drop,
    check_price_recovery,
    check_statistical_low,
)
from price_platform.store._price_event_types import PriceContext, PriceEventConfig, PriceHistoryPoint
from price_platform.store._price_statistics import build_daily_price_points, is_returning_from_spike
from price_platform.store.price_event_detector import KeywordEventFactory


class DummyEventType(StrEnum):
    ALL_TIME_LOW = "ALL_TIME_LOW"
    STATISTICAL_LOW = "STATISTICAL_LOW"
    PERIOD_LOW_30 = "PERIOD_LOW_30"
    PRICE_DROP = "PRICE_DROP"
    PRICE_RECOVERY = "PRICE_RECOVERY"
    FLEA_BARGAIN = "FLEA_BARGAIN"
    GOOD_USED_DEAL = "GOOD_USED_DEAL"


class DummyEventTypes:
    ALL_TIME_LOW = DummyEventType.ALL_TIME_LOW
    STATISTICAL_LOW = DummyEventType.STATISTICAL_LOW
    PRICE_DROP = DummyEventType.PRICE_DROP
    PRICE_RECOVERY = DummyEventType.PRICE_RECOVERY
    FLEA_BARGAIN = DummyEventType.FLEA_BARGAIN
    GOOD_USED_DEAL = DummyEventType.GOOD_USED_DEAL


@dataclass(frozen=True)
class DummyPriceRecord:
    price: int
    recorded_at: datetime
    is_used: bool = False
    store: str = "shop"
    url: str | None = "https://example.com/item"


def _build_context(
    *,
    now: datetime,
    current: DummyPriceRecord,
    full_new_history: list[DummyPriceRecord],
    stable_history_by_days: dict[int, list[PriceHistoryPoint]],
    all_time_lowest_new: DummyPriceRecord | None = None,
) -> PriceContext[DummyPriceRecord, Never]:
    return PriceContext(
        product_id="product-1",
        canonical_variant_key="variant-1",
        current_prices=[current],
        new_prices=[current],
        used_prices=[],
        all_time_lowest_new=all_time_lowest_new,
        period_lowest={30: None, 60: None, 90: None, 180: None, 365: None},
        price_history={days: full_new_history for days in stable_history_by_days},
        stable_price_history=stable_history_by_days,
        full_new_price_history=full_new_history,
        stable_full_new_price_history=stable_history_by_days[max(stable_history_by_days)],
        sold_records=[],
    )


def test_build_daily_price_points_uses_daily_median() -> None:
    day = datetime(2026, 4, 1, 10, 0, 0)
    history = [
        DummyPriceRecord(price=100, recorded_at=day),
        DummyPriceRecord(price=80, recorded_at=day + timedelta(hours=1)),
        DummyPriceRecord(price=120, recorded_at=day + timedelta(hours=2)),
    ]

    points = build_daily_price_points(history, mode="median")

    assert len(points) == 1
    assert points[0].price == 100


def test_check_statistical_low_emits_rarity_event() -> None:
    now = datetime(2026, 4, 6, 12, 0, 0)
    current = DummyPriceRecord(price=70, recorded_at=now)
    stable_history = [
        PriceHistoryPoint(price=70 if day == 10 else 100, recorded_at=now - timedelta(days=day + 1))
        for day in range(120)
    ]
    ctx = _build_context(
        now=now,
        current=current,
        full_new_history=[DummyPriceRecord(price=point.price, recorded_at=point.recorded_at) for point in stable_history],
        stable_history_by_days={365: stable_history},
        all_time_lowest_new=DummyPriceRecord(price=70, recorded_at=now - timedelta(days=11)),
    )

    draft = check_statistical_low(
        ctx,
        current,
        now,
        event_types=DummyEventTypes,
        config=PriceEventConfig(rarity_window_days=365),
        extra_fields={},
    )

    assert draft is not None
    assert draft.event_type == DummyEventType.STATISTICAL_LOW
    assert draft.rarity_tier == "VERY_HIGH"
    assert draft.percentile_rank is not None
    assert draft.percentile_rank <= 1.0


def test_check_price_drop_detects_large_immediate_drop() -> None:
    now = datetime(2026, 4, 6, 12, 0, 0)
    current = DummyPriceRecord(price=75, recorded_at=now)
    stable_history = [
        PriceHistoryPoint(price=100, recorded_at=now - timedelta(days=day + 3))
        for day in range(14)
    ]
    full_history = [DummyPriceRecord(price=100, recorded_at=point.recorded_at) for point in stable_history]
    ctx = _build_context(
        now=now,
        current=current,
        full_new_history=full_history,
        stable_history_by_days={14: stable_history},
        all_time_lowest_new=DummyPriceRecord(price=90, recorded_at=now - timedelta(days=30)),
    )

    draft = check_price_drop(
        ctx,
        current,
        now,
        event_types=DummyEventTypes,
        config=PriceEventConfig(),
        extra_fields={},
    )

    assert draft is not None
    assert draft.event_type == DummyEventType.PRICE_DROP
    assert draft.baseline_price == 100


def test_spike_reversion_is_not_treated_as_drop() -> None:
    assert is_returning_from_spike(
        baseline=100,
        recent_prices=[140],
        current_price=100,
        spike_threshold_percent=15.0,
        baseline_band_percent=3.0,
    )


def test_check_price_recovery_uses_sustained_days() -> None:
    now = datetime(2026, 4, 20, 12, 0, 0)
    current = DummyPriceRecord(price=96, recorded_at=now)
    stable_history = [
        PriceHistoryPoint(price=110, recorded_at=now - timedelta(days=20)),
        PriceHistoryPoint(price=105, recorded_at=now - timedelta(days=19)),
        PriceHistoryPoint(price=80, recorded_at=now - timedelta(days=10)),
        PriceHistoryPoint(price=92, recorded_at=now - timedelta(days=3)),
        PriceHistoryPoint(price=94, recorded_at=now - timedelta(days=2)),
        PriceHistoryPoint(price=95, recorded_at=now - timedelta(days=1)),
    ]
    ctx = _build_context(
        now=now,
        current=current,
        full_new_history=[DummyPriceRecord(price=point.price, recorded_at=point.recorded_at) for point in stable_history],
        stable_history_by_days={30: stable_history},
        all_time_lowest_new=DummyPriceRecord(price=80, recorded_at=now - timedelta(days=10)),
    )

    draft = check_price_recovery(
        ctx,
        current,
        now,
        event_types=DummyEventTypes,
        config=PriceEventConfig(),
        extra_fields={},
    )

    assert draft is not None
    assert draft.event_type == DummyEventType.PRICE_RECOVERY


@dataclass(frozen=True)
class DummyDetectedEvent:
    event_type: str
    product_id: str
    store: str
    price: int
    url: str | None
    recorded_at: datetime
    id: int | None = None
    priority: int = 0


def test_keyword_event_factory_filters_unknown_kwargs() -> None:
    now = datetime(2026, 4, 6, 12, 0, 0)

    def build_legacy_event(*, event_type: str, product_id: str, store: str, price: int, url: str | None, recorded_at: datetime) -> DummyDetectedEvent:
        return DummyDetectedEvent(
            event_type=event_type,
            product_id=product_id,
            store=store,
            price=price,
            url=url,
            recorded_at=recorded_at,
        )

    factory = KeywordEventFactory(build_legacy_event)
    draft = check_statistical_low(
        _build_context(
            now=now,
            current=DummyPriceRecord(price=70, recorded_at=now),
            full_new_history=[DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1)) for day in range(120)],
            stable_history_by_days={
                365: [PriceHistoryPoint(price=100, recorded_at=now - timedelta(days=day + 1)) for day in range(120)]
            },
            all_time_lowest_new=DummyPriceRecord(price=70, recorded_at=now - timedelta(days=200)),
        ),
        DummyPriceRecord(price=70, recorded_at=now),
        now,
        event_types=DummyEventTypes,
        config=PriceEventConfig(rarity_window_days=365),
        extra_fields={},
    )
    assert draft is not None
    event = factory.create_event(draft)

    assert event.product_id == "product-1"
