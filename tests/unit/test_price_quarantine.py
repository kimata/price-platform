"""価格品質ガード (F4) のテスト。"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from price_platform.store.fetcher_common import exclude_suspicious_prices
from price_platform.store.price_quarantine import PriceQuarantineStore, QuarantinedPrice


@dataclass(frozen=True)
class _Price:
    price: int
    title: str = "item"
    url: str = "https://example.com/item"


def test_exclude_records_quarantined_prices() -> None:
    recorded: list[QuarantinedPrice] = []
    prices = [_Price(price=100), _Price(price=10000), _Price(price=9_999_999)]

    result = exclude_suspicious_prices(
        prices,
        reference_price=10000,
        threshold_ratio_min=0.3,
        threshold_ratio_max=3.0,
        store_name="mercari",
        product_name="TD002G",
        quarantine_recorder=recorded.append,
    )

    assert [p.price for p in result] == [10000]
    assert len(recorded) == 2
    reasons = {entry.reason for entry in recorded}
    assert reasons == {"below_min_threshold", "above_max_threshold"}
    assert recorded[0].reference_price == 10000


def test_exclude_without_recorder_keeps_behavior() -> None:
    prices = [_Price(price=100), _Price(price=10000)]
    result = exclude_suspicious_prices(
        prices,
        reference_price=10000,
        threshold_ratio_min=0.3,
        threshold_ratio_max=3.0,
        store_name="mercari",
        product_name="TD002G",
    )
    assert [p.price for p in result] == [10000]


def test_quarantine_store_records_and_aggregates(tmp_path: pathlib.Path) -> None:
    store = PriceQuarantineStore(tmp_path / "quarantine.db")

    for _ in range(3):
        store.record(
            QuarantinedPrice(
                product_name="TD002G",
                store_name="mercari",
                price=100,
                reference_price=10000,
                reason="below_min_threshold",
            )
        )
    store.record(
        QuarantinedPrice(
            product_name="TD002G",
            store_name="amazon",
            price=9_999_999,
            reason="above_max_threshold",
        )
    )

    stats = store.get_stats(days=7)
    by_key = {(s.store_name, s.reason): s.count for s in stats}
    assert by_key[("mercari", "below_min_threshold")] == 3
    assert by_key[("amazon", "above_max_threshold")] == 1

    assert store.cleanup_old(days=0) == 4
