"""Context building helpers for price event detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Generic

from price_platform.platform import clock

from ._price_event_types import PriceContext, PriceEventConfig, PriceRecordT, PriceStoreProtocol, SoldRecordT
from ._price_statistics import build_daily_price_points


@dataclass(frozen=True)
class PriceContextBuilder(Generic[PriceRecordT, SoldRecordT]):
    price_store: PriceStoreProtocol[PriceRecordT, SoldRecordT]
    config: PriceEventConfig

    def build(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
        *,
        selection_key: str | None = None,
    ) -> PriceContext[PriceRecordT, SoldRecordT]:
        new_prices = [p for p in current_prices if not p.is_used]
        used_prices = [p for p in current_prices if p.is_used]
        history_days = {
            7,
            30,
            max(
                self.config.rarity_window_days,
                self.config.price_drop_baseline_window_days,
                self.config.price_recovery_window_days,
            ),
        }
        history_days.update(self.config.period_low_days)
        full_history = self.price_store.get_price_history(
            product_id, days=max(history_days), selection_key=selection_key
        )

        now = clock.now()
        price_history: dict[int, list[PriceRecordT]] = {}
        stable_price_history = {}
        for days in history_days:
            cutoff = now - timedelta(days=days)
            price_history[days] = [p for p in full_history if p.recorded_at >= cutoff]
            stable_price_history[days] = build_daily_price_points(
                [p for p in price_history[days] if not p.is_used],
                mode=self.config.daily_price_mode,
            )

        full_new_price_history = [p for p in full_history if not p.is_used]
        stable_full_new_price_history = build_daily_price_points(
            full_new_price_history,
            mode=self.config.daily_price_mode,
        )

        all_time_lowest_new = self.price_store.get_lowest_price(
            product_id, is_used=False, selection_key=selection_key
        )
        period_lowest: dict[int, PriceRecordT | None] = {}
        for days in self.config.period_low_days:
            history = price_history.get(days, [])
            new_history = [p for p in history if not p.is_used]
            period_lowest[days] = min(new_history, key=lambda p: p.price) if new_history else None

        sold_records = self.price_store.get_sold_records(
            product_id, limit=20, selection_key=selection_key
        )
        return PriceContext(
            product_id=product_id,
            canonical_variant_key=self.config.canonical_variant_key_builder(product_id, current_prices),
            current_prices=current_prices,
            new_prices=new_prices,
            used_prices=used_prices,
            all_time_lowest_new=all_time_lowest_new,
            period_lowest=period_lowest,
            price_history=price_history,
            stable_price_history=stable_price_history,
            full_new_price_history=full_new_price_history,
            stable_full_new_price_history=stable_full_new_price_history,
            sold_records=sold_records,
        )
