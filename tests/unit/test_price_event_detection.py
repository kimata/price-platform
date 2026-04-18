from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Never

from price_platform.store._price_event_rules import (
    check_price_drop,
    check_price_recovery,
    check_statistical_low,
)
from price_platform.store._price_event_types import PriceContext, PriceEventConfig, PriceHistoryPoint
from price_platform.store._price_statistics import build_daily_price_points, is_returning_from_spike
from price_platform.store.price_event_detector import KeywordEventFactory, PriceEventDetector


class DummyEventType(StrEnum):
    ALL_TIME_LOW = "ALL_TIME_LOW"
    STATISTICAL_LOW = "STATISTICAL_LOW"
    PERIOD_LOW_30 = "PERIOD_LOW_30"
    PERIOD_LOW_60 = "PERIOD_LOW_60"
    PERIOD_LOW_90 = "PERIOD_LOW_90"
    PERIOD_LOW_180 = "PERIOD_LOW_180"
    PERIOD_LOW_365 = "PERIOD_LOW_365"
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
    variant_id: str | None = None


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
        price_history=dict.fromkeys(stable_history_by_days, full_new_history),
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


def test_keyword_event_factory_passes_through_var_keyword() -> None:
    """**kwargs シグネチャの関数にはフィルタリングせず全引数を渡す."""
    from typing import Any

    now = datetime(2026, 4, 6, 12, 0, 0)

    def build_event_via_kwargs(**kwargs: Any) -> DummyDetectedEvent:
        accepted = {
            k: v for k, v in kwargs.items() if k in DummyDetectedEvent.__dataclass_fields__
        }
        return DummyDetectedEvent(**accepted)

    factory = KeywordEventFactory(build_event_via_kwargs)
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
    assert event.price == 70


# --- Variant-aware detection tests ---


@dataclass(frozen=True)
class DummyDetectedEventFull:
    event_type: str
    product_id: str
    store: str
    price: int
    url: str | None
    recorded_at: datetime
    id: int | None = None
    priority: int = 0
    variant_id: str | None = None


class InMemoryPriceStore:
    """selection_key 対応のインメモリ PriceStore."""

    def __init__(self, prices: list[DummyPriceRecord], sold: list[Any] | None = None) -> None:
        self._prices = prices
        self._sold = sold or []

    def _filter(self, records: list[DummyPriceRecord], product_id: str, selection_key: str | None) -> list[DummyPriceRecord]:
        result = [p for p in records if getattr(p, "product_id", product_id) == product_id]
        if selection_key is not None:
            result = [p for p in result if p.variant_id == selection_key]
        return result

    def get_current_prices(self, product_id: str, *, selection_key: str | None = None) -> list[DummyPriceRecord]:
        current: dict[tuple[str | None, str, bool], DummyPriceRecord] = {}
        for p in self._filter(self._prices, product_id, selection_key):
            key = (p.variant_id, p.store, p.is_used)
            if key not in current or p.recorded_at > current[key].recorded_at:
                current[key] = p
        return list(current.values())

    def get_price_history(self, product_id: str, days: int, *, selection_key: str | None = None) -> list[DummyPriceRecord]:
        from price_platform.platform import clock

        cutoff = clock.now() - timedelta(days=days)
        return [
            p for p in self._filter(self._prices, product_id, selection_key)
            if p.recorded_at >= cutoff
        ]

    def get_lowest_price(self, product_id: str, *, is_used: bool, selection_key: str | None = None) -> DummyPriceRecord | None:
        filtered = [
            p for p in self._filter(self._prices, product_id, selection_key)
            if p.is_used == is_used
        ]
        return min(filtered, key=lambda p: p.price) if filtered else None

    def get_sold_records(self, product_id: str, *, limit: int = 20, selection_key: str | None = None) -> list[Any]:
        return self._sold[:limit]


class InMemoryEventStore:
    """最小限のインメモリ PriceEventStore."""

    def __init__(self) -> None:
        self._events: list[Any] = []
        self._next_id = 1

    def has_recent_similar_price_event(
        self, product_id: str, store: Any, price: int, days: int = 14, tolerance: int = 100
    ) -> bool:
        return False

    def get_recent_event_for_product(self, product_id: str, hours: int) -> Any | None:
        return None

    def save_event(self, event: Any) -> int:
        event_id = self._next_id
        self._next_id += 1
        self._events.append(replace(event, id=event_id))
        return event_id

    def suppress_event(self, event_id: int, superseded_by: int) -> None:
        pass


def _make_variant_detector(
    prices: list[DummyPriceRecord],
    *,
    with_variant_extractor: bool = True,
) -> PriceEventDetector[DummyDetectedEventFull, DummyPriceRecord, Never]:
    """バリアント対応の PriceEventDetector を構築する."""
    config = PriceEventConfig(
        variant_key_extractor=(lambda r: r.variant_id) if with_variant_extractor else (lambda _: None),
        all_time_low_min_days=5,
    )

    def event_factory(**kwargs: Any) -> DummyDetectedEventFull:
        accepted = {k: v for k, v in kwargs.items() if k in DummyDetectedEventFull.__dataclass_fields__}
        return DummyDetectedEventFull(**accepted)

    return PriceEventDetector(
        price_store=InMemoryPriceStore(prices),
        event_store=InMemoryEventStore(),
        event_types=DummyEventTypes,
        period_event_map={
            30: DummyEventType.PERIOD_LOW_30,
            60: DummyEventType.PERIOD_LOW_60,
            90: DummyEventType.PERIOD_LOW_90,
            180: DummyEventType.PERIOD_LOW_180,
            365: DummyEventType.PERIOD_LOW_365,
        },
        flea_market_stores=(),
        event_factory=event_factory,
        event_extra_fields=lambda record: {"variant_id": record.variant_id},
        config=config,
    )


def test_detect_events_separates_variants() -> None:
    """バリアント別にイベント検出が分離されることを確認する.

    variant_A は価格変動なし (100円固定) → イベントなし
    variant_B は大幅な値下げ (100円 → 50円) → STATISTICAL_LOW イベント検出
    """
    from price_platform.platform import clock

    now = clock.now()

    prices: list[DummyPriceRecord] = []
    # variant_A: 100円で安定 (120日分) → 統計的にも安定
    for day in range(120):
        prices.append(DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1), variant_id="A"))
    prices.append(DummyPriceRecord(price=100, recorded_at=now, variant_id="A"))

    # variant_B: 100円で安定 (120日分) → 最新のみ50円に値下げ
    for day in range(120):
        prices.append(DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1), variant_id="B"))
    prices.append(DummyPriceRecord(price=50, recorded_at=now, variant_id="B"))

    detector = _make_variant_detector(prices, with_variant_extractor=True)
    events = detector.detect_events("product-1")

    # variant_B のイベントのみ検出される
    assert events
    for event in events:
        assert event.variant_id == "B", f"variant_A のイベントが誤って検出された: {event}"


def test_detect_events_without_variant_extractor_mixes_data() -> None:
    """variant_key_extractor 未設定時は全バリアントが混在する（従来の動作）."""
    from price_platform.platform import clock

    now = clock.now()

    prices: list[DummyPriceRecord] = []
    for day in range(120):
        prices.append(DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1), variant_id="A"))
    prices.append(DummyPriceRecord(price=100, recorded_at=now, variant_id="A"))

    for day in range(120):
        prices.append(DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1), variant_id="B"))
    prices.append(DummyPriceRecord(price=50, recorded_at=now, variant_id="B"))

    detector = _make_variant_detector(prices, with_variant_extractor=False)
    events = detector.detect_events("product-1")

    # extractor 未設定: 全バリアント混在で検出される
    # cheapest_new は variant_B の 50円になるが、variant_id 区別なくイベント生成
    # 例外が起きないことを確認（イベントが出るか出ないかはルール次第）
    assert isinstance(events, list)


def test_detect_events_variant_isolation_prevents_cross_contamination() -> None:
    """バリアント A の履歴がバリアント B の検出コンテキストに混入しないことを確認.

    variant_A: 20円で安定（安い） → variant_B の基準に影響してはならない
    variant_B: 100円で安定 → 最新50円に値下げ → STATISTICAL_LOW 検出
    混入があると variant_B の履歴に20円が含まれ、50円の統計的異常度が下がる。
    """
    from price_platform.platform import clock

    now = clock.now()

    prices: list[DummyPriceRecord] = []
    # variant_A: 20円で安定 (120日分)
    for day in range(120):
        prices.append(DummyPriceRecord(price=20, recorded_at=now - timedelta(days=day + 1), variant_id="A"))
    prices.append(DummyPriceRecord(price=20, recorded_at=now, variant_id="A"))

    # variant_B: 100円で安定 (120日分) → 最新は50円
    for day in range(120):
        prices.append(DummyPriceRecord(price=100, recorded_at=now - timedelta(days=day + 1), variant_id="B"))
    prices.append(DummyPriceRecord(price=50, recorded_at=now, variant_id="B"))

    detector = _make_variant_detector(prices, with_variant_extractor=True)
    events = detector.detect_events("product-1")

    # variant_B のイベントが検出される（variant_A の20円履歴に汚染されていない）
    variant_b_events = [e for e in events if e.variant_id == "B"]
    assert variant_b_events, "variant_B の統計的異常が検出されるべき"
    assert variant_b_events[0].price == 50
