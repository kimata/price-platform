"""イベント抑制まわりのテスト。

- BasePriceEventStore の抑制系クエリが selection (バリアント) 単位で照会すること (B4)
- apply_event_suppression の 3 分岐 (類似抑制 / 同一状態抑制 / priority 上書き)
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from price_platform.platform import clock
from price_platform.store._price_event_suppression import apply_event_suppression
from price_platform.store._price_event_types import PriceEventConfig
from price_platform.store.price_event_store import BasePriceEventStore


class _EventType(StrEnum):
    PRICE_DROP = "PRICE_DROP"
    ALL_TIME_LOW = "ALL_TIME_LOW"


@dataclass(frozen=True)
class _Event:
    event_type: _EventType
    priority: int
    product_id: str
    store: str
    price: int
    recorded_at: datetime
    url: str | None = None
    previous_price: int | None = None
    reference_price: int | None = None
    change_percent: float | None = None
    period_days: int | None = None
    percentile_rank: float | None = None
    rarity_tier: str | None = None
    baseline_price: int | None = None
    sample_days: int | None = None
    sample_count: int | None = None
    rarity_window_days: int | None = None
    detector_version: str | None = None
    canonical_variant_key: str | None = None
    event_family: str | None = None
    comparison_basis: str | None = None
    severity: str | None = None
    variant_id: str | None = None
    suppressed: bool = False
    superseded_by: int | None = None
    twitter_posted: bool = False
    twitter_enabled: bool = True
    id: int | None = None


def _make_store(tmp_path: pathlib.Path) -> BasePriceEventStore[dict[str, Any]]:
    return BasePriceEventStore(
        db_path=tmp_path / "events.db",
        selection_column="variant_id",
        event_factory=lambda row, selection: {"row": dict(row), "selection": selection},
    )


def _make_event(*, variant_id: str | None, price: int = 10000, priority: int = 3) -> _Event:
    return _Event(
        event_type=_EventType.PRICE_DROP,
        priority=priority,
        product_id="p1",
        store="shop",
        price=price,
        recorded_at=clock.now(),
        variant_id=variant_id,
    )


class TestSelectionAwareSuppressionQueries:
    """B4 回帰: 抑制系クエリが selection 単位で照会されること."""

    def test_similar_event_does_not_match_other_variant(self, tmp_path: pathlib.Path) -> None:
        store = _make_store(tmp_path)
        store.save_event(_make_event(variant_id="A", price=10000))

        # 同一バリアントの近い価格 → 類似イベントあり
        assert store.has_recent_similar_price_event("p1", "shop", 10050, selection_key="A")
        # 別バリアントの近い価格 → 抑制されない
        assert not store.has_recent_similar_price_event("p1", "shop", 10050, selection_key="B")

    def test_recent_event_does_not_match_other_variant(self, tmp_path: pathlib.Path) -> None:
        store = _make_store(tmp_path)
        store.save_event(_make_event(variant_id="A"))

        assert store.get_recent_event_for_product("p1", hours=24, selection_key="A") is not None
        assert store.get_recent_event_for_product("p1", hours=24, selection_key="B") is None

    def test_null_selection_matches_null_rows_only(self, tmp_path: pathlib.Path) -> None:
        store = _make_store(tmp_path)
        store.save_event(_make_event(variant_id=None))

        assert store.get_recent_event_for_product("p1", hours=24, selection_key=None) is not None
        assert store.get_recent_event_for_product("p1", hours=24, selection_key="A") is None

    def test_no_selection_column_ignores_selection_key(self, tmp_path: pathlib.Path) -> None:
        store = BasePriceEventStore(
            db_path=tmp_path / "events.db",
            selection_column=None,
            event_factory=lambda row, selection: {"row": dict(row), "selection": selection},
        )
        store.save_event(_make_event(variant_id=None))

        # selection 列を持たない構成では selection_key は無視される
        assert store.get_recent_event_for_product("p1", hours=24, selection_key="A") is not None


@dataclass
class _FakeEventStore:
    """apply_event_suppression の分岐検証用フェイク."""

    similar: bool = False
    existing: _Event | None = None
    saved: list[_Event] = field(default_factory=list)
    suppressed: list[tuple[int, int]] = field(default_factory=list)
    seen_selection_keys: list[str | None] = field(default_factory=list)

    def has_recent_similar_price_event(
        self,
        product_id: str,
        store: Any,
        price: int,
        days: int = 14,
        tolerance: int = 100,
        *,
        selection_key: str | None = None,
    ) -> bool:
        self.seen_selection_keys.append(selection_key)
        return self.similar

    def get_recent_event_for_product(
        self, product_id: str, hours: int, *, selection_key: str | None = None
    ) -> _Event | None:
        self.seen_selection_keys.append(selection_key)
        return self.existing

    def save_event(self, event: _Event) -> int:
        self.saved.append(event)
        return len(self.saved)

    def suppress_event(self, event_id: int, superseded_by: int) -> None:
        self.suppressed.append((event_id, superseded_by))


class TestApplyEventSuppressionBranches:
    """抑制ロジック 3 分岐の検証 (従来テストゼロだった箇所)."""

    def test_similar_price_event_is_discarded(self) -> None:
        event_store = _FakeEventStore(similar=True)
        result = apply_event_suppression(
            event_store=event_store,
            product_id="p1",
            detected=[_make_event(variant_id="A")],
            config=PriceEventConfig(),
            selection_key="A",
        )

        assert result == []
        assert event_store.saved == []
        assert event_store.seen_selection_keys == ["A"]

    def test_new_event_is_saved_when_no_existing(self) -> None:
        event_store = _FakeEventStore()
        result = apply_event_suppression(
            event_store=event_store,
            product_id="p1",
            detected=[_make_event(variant_id="A")],
            config=PriceEventConfig(),
            selection_key="A",
        )

        assert len(result) == 1
        assert result[0].id == 1
        assert event_store.seen_selection_keys == ["A", "A"]

    def test_same_state_event_is_suppressed(self) -> None:
        existing = _make_event(variant_id="A", price=10000, priority=3)
        event_store = _FakeEventStore(existing=existing)
        result = apply_event_suppression(
            event_store=event_store,
            product_id="p1",
            detected=[_make_event(variant_id="A", price=10050, priority=3)],  # tolerance 100 以内
            config=PriceEventConfig(),
            selection_key="A",
        )

        assert result == []
        assert event_store.saved == []

    def test_higher_priority_event_supersedes_existing(self) -> None:
        existing = _Event(
            event_type=_EventType.PRICE_DROP,
            priority=5,
            product_id="p1",
            store="shop",
            price=20000,
            recorded_at=clock.now(),
            id=99,
        )
        event_store = _FakeEventStore(existing=existing)
        result = apply_event_suppression(
            event_store=event_store,
            product_id="p1",
            detected=[
                _Event(
                    event_type=_EventType.ALL_TIME_LOW,
                    priority=1,
                    product_id="p1",
                    store="shop",
                    price=9000,
                    recorded_at=clock.now(),
                )
            ],
            config=PriceEventConfig(),
        )

        assert len(result) == 1
        assert event_store.suppressed == [(99, 1)]


def test_get_event_counts_by_type(tmp_path: pathlib.Path) -> None:
    """F1: 種別別の検出数集計 (検出パイプライン自己監視用)."""
    store = _make_store(tmp_path)
    store.save_event(_make_event(variant_id="A"))
    store.save_event(_make_event(variant_id="B", price=20000))

    counts = store.get_event_counts_by_type(days=7)

    assert counts == {"PRICE_DROP": 2}
