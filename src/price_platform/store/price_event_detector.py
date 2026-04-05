"""Shared price event detection core."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Generic

from price_platform.platform import clock

from ._price_event_context import PriceContextBuilder
from ._price_event_rules import (
    check_all_time_low,
    check_flea_bargain,
    check_good_used_deal,
    check_period_low,
    check_price_drop,
    check_price_recovery,
)
from ._price_event_suppression import apply_event_suppression
from ._price_event_types import (
    EventFactoryProtocol,
    EventMetadataAdapter,
    PriceContext,
    PriceEventConfig,
    PriceEventDraft,
    PriceEventStoreProtocol,
    PriceEventT,
    PriceRecordProtocol,
    PriceRecordT,
    PriceStoreProtocol,
    SoldRecordProtocol,
    SoldRecordT,
)

logger = logging.getLogger(__name__)


class KeywordEventFactory(Generic[PriceEventT]):
    """Adapter from ``**kwargs`` callables to the typed event-factory protocol."""

    def __init__(self, builder: Callable[..., PriceEventT]):
        self._builder = builder

    def create_event(self, draft: PriceEventDraft) -> PriceEventT:
        return self._builder(**draft.to_kwargs())


class PriceEventDetector(Generic[PriceEventT, PriceRecordT, SoldRecordT]):
    """Detect price events from app-specific price records."""

    def __init__(
        self,
        price_store: PriceStoreProtocol[PriceRecordT, SoldRecordT],
        event_store: PriceEventStoreProtocol[PriceEventT],
        *,
        event_types: Any,
        period_event_map: Mapping[int, Any],
        flea_market_stores: Sequence[Any],
        event_factory: EventFactoryProtocol[PriceEventT] | Callable[..., PriceEventT],
        event_extra_fields: EventMetadataAdapter[PriceRecordT] | None = None,
        config: PriceEventConfig | None = None,
    ):
        self.price_store = price_store
        self.event_store = event_store
        self.event_types = event_types
        self.period_event_map = dict(period_event_map)
        self.flea_market_stores = frozenset(flea_market_stores)
        if hasattr(event_factory, "create_event"):
            self.event_factory = event_factory
        else:
            self.event_factory = KeywordEventFactory(event_factory)
        self.event_extra_fields = event_extra_fields or (lambda _record: {})
        self.config = config or PriceEventConfig()

    def _build_event(self, draft: PriceEventDraft) -> PriceEventT:
        return self.event_factory.create_event(draft)

    def _build_price_context(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> PriceContext[PriceRecordT, SoldRecordT]:
        return PriceContextBuilder(self.price_store, self.config).build(product_id, current_prices)

    def _detect_events(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        now,
    ) -> list[PriceEventT]:
        drafts: list[PriceEventDraft] = []

        if ctx.new_prices:
            cheapest_new = min(ctx.new_prices, key=lambda p: p.price)
            cheapest_new_metadata = dict(self.event_extra_fields(cheapest_new))

            all_time_event = check_all_time_low(
                ctx,
                cheapest_new,
                now,
                event_types=self.event_types,
                extra_fields=cheapest_new_metadata,
            )
            if all_time_event:
                drafts.append(all_time_event)

            if not all_time_event:
                period_event = check_period_low(
                    ctx,
                    cheapest_new,
                    now,
                    period_event_map=self.period_event_map,
                    config=self.config,
                    extra_fields=cheapest_new_metadata,
                )
                if period_event:
                    drafts.append(period_event)

            drop_event = check_price_drop(
                ctx,
                cheapest_new,
                now,
                event_types=self.event_types,
                config=self.config,
                extra_fields=cheapest_new_metadata,
            )
            if drop_event:
                drafts.append(drop_event)

            recovery_event = check_price_recovery(
                ctx,
                cheapest_new,
                now,
                event_types=self.event_types,
                config=self.config,
                extra_fields=cheapest_new_metadata,
            )
            if recovery_event:
                drafts.append(recovery_event)

        if ctx.used_prices and ctx.new_prices:
            cheapest_used = min(ctx.used_prices, key=lambda p: p.price)
            cheapest_new = min(ctx.new_prices, key=lambda p: p.price)
            used_deal_event = check_good_used_deal(
                ctx.product_id,
                cheapest_used,
                cheapest_new.price,
                now,
                event_types=self.event_types,
                config=self.config,
                extra_fields=dict(self.event_extra_fields(cheapest_used)),
            )
            if used_deal_event:
                drafts.append(used_deal_event)

        for price in ctx.used_prices:
            if price.store in self.flea_market_stores:
                bargain_event = check_flea_bargain(
                    ctx,
                    price,
                    now,
                    event_types=self.event_types,
                    config=self.config,
                    extra_fields=dict(self.event_extra_fields(price)),
                )
                if bargain_event:
                    drafts.append(bargain_event)
                    break

        detected = [self._build_event(draft) for draft in drafts]
        detected.sort(key=lambda event: event.priority)
        return detected

    def detect_events_for_product(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices)
        now = clock.now()
        detected = self._detect_events(ctx, now)
        return apply_event_suppression(
            event_store=self.event_store,
            product_id=product_id,
            detected=detected,
            config=self.config,
        )

    def detect_events_only(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices)
        now = clock.now()
        return self._detect_events(ctx, now)

    def detect_events(self, product_id: str) -> list[PriceEventT]:
        current_prices = self.price_store.get_current_prices(product_id)
        return self.detect_events_for_product(product_id, current_prices)
