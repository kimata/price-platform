"""Context building helpers for price event detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Generic

from price_platform.platform import clock

from ._price_event_types import PriceContext, PriceEventConfig, PriceRecordT, PriceStoreProtocol, SoldRecordT


@dataclass(frozen=True)
class PriceContextBuilder(Generic[PriceRecordT, SoldRecordT]):
    price_store: PriceStoreProtocol[PriceRecordT, SoldRecordT]
    config: PriceEventConfig

    def build(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> PriceContext[PriceRecordT, SoldRecordT]:
        new_prices = [p for p in current_prices if not p.is_used]
        used_prices = [p for p in current_prices if p.is_used]
        history_days = {7, 30}
        history_days.update(self.config.period_low_days)
        max_days = max(history_days)
        full_history = self.price_store.get_price_history(product_id, days=max_days)

        now = clock.now()
        price_history: dict[int, list[PriceRecordT]] = {}
        for days in history_days:
            cutoff = now - timedelta(days=days)
            price_history[days] = [p for p in full_history if p.recorded_at >= cutoff]

        all_time_lowest_new = self.price_store.get_lowest_price(product_id, is_used=False)
        period_lowest: dict[int, PriceRecordT | None] = {}
        for days in self.config.period_low_days:
            history = price_history.get(days, [])
            new_history = [p for p in history if not p.is_used]
            period_lowest[days] = min(new_history, key=lambda p: p.price) if new_history else None

        sold_records = self.price_store.get_sold_records(product_id, limit=20)
        return PriceContext(
            product_id=product_id,
            current_prices=current_prices,
            new_prices=new_prices,
            used_prices=used_prices,
            all_time_lowest_new=all_time_lowest_new,
            period_lowest=period_lowest,
            price_history=price_history,
            sold_records=sold_records,
        )
