"""Shared price event detection core."""

from __future__ import annotations

import inspect
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
    check_statistical_low,
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
    PriceRecordT,
    PriceStoreProtocol,
    SoldRecordT,
)

logger = logging.getLogger(__name__)

STANDARD_PERIOD_LOW_WINDOWS: tuple[int, ...] = (30, 60, 90, 180, 365)
STANDARD_FLEA_MARKET_STORE_NAMES: tuple[str, ...] = ("MERCARI", "RAKUMA", "PAYPAY")


def build_standard_period_event_map(event_types: Any) -> dict[int, Any]:
    """Build the conventional PERIOD_LOW_* mapping for consumer apps."""
    return {
        days: getattr(event_types, f"PERIOD_LOW_{days}")
        for days in STANDARD_PERIOD_LOW_WINDOWS
    }


def build_standard_flea_market_stores(store_types: Any) -> tuple[Any, ...]:
    """Resolve the conventional flea-market store members from an enum-like type."""
    return tuple(getattr(store_types, name) for name in STANDARD_FLEA_MARKET_STORE_NAMES)


class KeywordEventFactory(Generic[PriceEventT]):
    """Adapter from ``**kwargs`` callables to the typed event-factory protocol."""

    def __init__(self, builder: Callable[..., PriceEventT]):
        self._builder = builder
        sig = inspect.signature(builder)
        self._has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        self._allowed_kwargs = set(sig.parameters)

    def create_event(self, draft: PriceEventDraft) -> PriceEventT:
        payload = draft.to_kwargs()
        if self._has_var_keyword:
            return self._builder(**payload)
        filtered = {key: value for key, value in payload.items() if key in self._allowed_kwargs}
        return self._builder(**filtered)


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
        self.event_factory: EventFactoryProtocol[PriceEventT]
        if hasattr(event_factory, "create_event"):
            self.event_factory = event_factory  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        else:
            self.event_factory = KeywordEventFactory(event_factory)  # type: ignore[arg-type]
        self.event_extra_fields: EventMetadataAdapter[PriceRecordT] = event_extra_fields or (lambda record: {})
        self.config = config or PriceEventConfig()

    def _build_event(self, draft: PriceEventDraft) -> PriceEventT:
        return self.event_factory.create_event(draft)

    def _build_price_context(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
        *,
        selection_key: str | None = None,
    ) -> PriceContext[PriceRecordT, SoldRecordT]:
        return PriceContextBuilder(self.price_store, self.config).build(
            product_id, current_prices, selection_key=selection_key
        )

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
                config=self.config,
                extra_fields=cheapest_new_metadata,
            )
            if all_time_event:
                drafts.append(all_time_event)

            statistical_event = check_statistical_low(
                ctx,
                cheapest_new,
                now,
                event_types=self.event_types,
                config=self.config,
                extra_fields=cheapest_new_metadata,
            )
            if statistical_event:
                drafts.append(statistical_event)

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
        *,
        selection_key: str | None = None,
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices, selection_key=selection_key)
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
        *,
        selection_key: str | None = None,
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices, selection_key=selection_key)
        now = clock.now()
        return self._detect_events(ctx, now)

    def _group_by_variant(
        self, prices: list[PriceRecordT]
    ) -> dict[str | None, list[PriceRecordT]]:
        """Group prices by variant key extracted via config.variant_key_extractor."""
        groups: dict[str | None, list[PriceRecordT]] = {}
        for price in prices:
            key = self.config.variant_key_extractor(price)
            groups.setdefault(key, []).append(price)
        return groups

    def detect_events(self, product_id: str) -> list[PriceEventT]:
        current_prices = self.price_store.get_current_prices(product_id)

        variant_groups = self._group_by_variant(current_prices)
        has_variants = len(variant_groups) > 1 or next(iter(variant_groups), None) is not None

        if not has_variants:
            return self.detect_events_for_product(product_id, current_prices)

        all_events: list[PriceEventT] = []
        for variant_key, variant_prices in variant_groups.items():
            events = self.detect_events_for_product(
                product_id, variant_prices, selection_key=variant_key
            )
            all_events.extend(events)
        return all_events
