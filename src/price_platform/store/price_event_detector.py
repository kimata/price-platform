"""Shared price event detection core."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Generic, Protocol, TypeVar

import my_lib.time

logger = logging.getLogger(__name__)

StoreTypeT = TypeVar("StoreTypeT")
PriceEventT = TypeVar("PriceEventT")
PriceRecordT = TypeVar("PriceRecordT", bound="PriceRecordProtocol[Any]")
SoldRecordT = TypeVar("SoldRecordT", bound="SoldRecordProtocol")


class PriceRecordProtocol(Protocol[StoreTypeT]):
    """Minimal price-record surface required by the detector."""

    price: int
    is_used: bool
    store: StoreTypeT
    url: str
    recorded_at: datetime


class SoldRecordProtocol(Protocol):
    """Minimal sold-record surface required by the detector."""

    price: int


class PriceStoreProtocol(Protocol[PriceRecordT, SoldRecordT]):
    """Price-store operations required by the detector."""

    def get_price_history(self, product_id: str, days: int) -> list[PriceRecordT]: ...

    def get_lowest_price(self, product_id: str, is_used: bool) -> PriceRecordT | None: ...

    def get_sold_records(self, product_id: str, limit: int = 20) -> list[SoldRecordT]: ...

    def get_current_prices(self, product_id: str) -> list[PriceRecordT]: ...


class PriceEventStoreProtocol(Protocol[PriceEventT]):
    """Price-event store operations required by the detector."""

    def has_recent_similar_price_event(
        self,
        product_id: str,
        store: Any,
        price: int,
        *,
        days: int,
        tolerance: int,
    ) -> bool: ...

    def get_recent_event_for_product(self, product_id: str, hours: int) -> PriceEventT | None: ...

    def save_event(self, event: PriceEventT) -> int: ...

    def suppress_event(self, event_id: int, suppressor_id: int) -> None: ...


@dataclass
class PriceContext(Generic[PriceRecordT, SoldRecordT]):
    """Aggregated price data for event detection."""

    product_id: str
    current_prices: list[PriceRecordT]
    new_prices: list[PriceRecordT]
    used_prices: list[PriceRecordT]
    all_time_lowest_new: PriceRecordT | None
    period_lowest: dict[int, PriceRecordT | None]
    price_history: dict[int, list[PriceRecordT]]
    sold_records: list[SoldRecordT]


@dataclass
class PriceEventConfig:
    """Configuration for price event detection."""

    period_low_days: tuple[int, ...] = (30, 60, 90, 180, 365)
    price_drop_threshold_percent: float = 10.0
    good_used_ratio_max: float = 0.5
    flea_bargain_threshold_percent: float = 20.0
    price_recovery_threshold_percent: float = 5.0
    price_recovery_min_days_after_low: int = 7
    price_recovery_consecutive_rises: int = 3
    price_recovery_consecutive_min_percent: float = 5.0
    suppression_window_hours: int = 24
    same_price_suppression_days: int = 14
    same_price_tolerance: int = 100


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
        event_factory: Callable[..., PriceEventT],
        event_extra_fields: Callable[[PriceRecordT], Mapping[str, object | None]] | None = None,
        config: PriceEventConfig | None = None,
    ):
        self.price_store = price_store
        self.event_store = event_store
        self.event_types = event_types
        self.period_event_map = dict(period_event_map)
        self.flea_market_stores = frozenset(flea_market_stores)
        self.event_factory = event_factory
        self.event_extra_fields = event_extra_fields or (lambda _record: {})
        self.config = config or PriceEventConfig()

    def _build_event(self, record: PriceRecordT, **kwargs: object) -> PriceEventT:
        return self.event_factory(**kwargs, **self.event_extra_fields(record))

    def _build_price_context(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> PriceContext[PriceRecordT, SoldRecordT]:
        """Build aggregated price context with a single batch of DB queries."""
        new_prices = [p for p in current_prices if not p.is_used]
        used_prices = [p for p in current_prices if p.is_used]

        history_days = {7, 30}
        history_days.update(self.config.period_low_days)
        max_days = max(history_days)

        full_history = self.price_store.get_price_history(product_id, days=max_days)

        now = my_lib.time.now()
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

    def _detect_events(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        now: datetime,
    ) -> list[PriceEventT]:
        detected: list[PriceEventT] = []

        if ctx.new_prices:
            cheapest_new = min(ctx.new_prices, key=lambda p: p.price)

            all_time_event = self._check_all_time_low(ctx, cheapest_new, now)
            if all_time_event:
                detected.append(all_time_event)

            if not all_time_event:
                period_event = self._check_period_low(ctx, cheapest_new, now)
                if period_event:
                    detected.append(period_event)

            drop_event = self._check_price_drop(ctx, cheapest_new, now)
            if drop_event:
                detected.append(drop_event)

            recovery_event = self._check_price_recovery(ctx, cheapest_new, now)
            if recovery_event:
                detected.append(recovery_event)

        if ctx.used_prices and ctx.new_prices:
            cheapest_used = min(ctx.used_prices, key=lambda p: p.price)
            cheapest_new = min(ctx.new_prices, key=lambda p: p.price)

            used_deal_event = self._check_good_used_deal(
                ctx.product_id, cheapest_used, cheapest_new.price, now
            )
            if used_deal_event:
                detected.append(used_deal_event)

        for price in ctx.used_prices:
            if price.store in self.flea_market_stores:
                bargain_event = self._check_flea_bargain(ctx, price, now)
                if bargain_event:
                    detected.append(bargain_event)
                    break

        detected.sort(key=lambda event: getattr(event, "priority"))
        return detected

    def detect_events_for_product(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices)
        now = my_lib.time.now()
        detected = self._detect_events(ctx, now)
        return self._apply_suppression(product_id, detected)

    def detect_events_only(
        self,
        product_id: str,
        current_prices: list[PriceRecordT],
    ) -> list[PriceEventT]:
        if not current_prices:
            return []

        ctx = self._build_price_context(product_id, current_prices)
        now = my_lib.time.now()
        return self._detect_events(ctx, now)

    def _check_all_time_low(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        current: PriceRecordT,
        now: datetime,
    ) -> PriceEventT | None:
        lowest = ctx.all_time_lowest_new
        if lowest is None or current.price >= lowest.price:
            return None

        logger.info("[ALL_TIME_LOW] %s: %s円 < %s円", ctx.product_id, f"{current.price:,}", f"{lowest.price:,}")
        return self._build_event(
            current,
            event_type=self.event_types.ALL_TIME_LOW,
            product_id=ctx.product_id,
            store=current.store,
            price=current.price,
            url=current.url,
            previous_price=lowest.price,
            recorded_at=now,
        )

    def _check_period_low(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        current: PriceRecordT,
        now: datetime,
    ) -> PriceEventT | None:
        for days in sorted(self.config.period_low_days, reverse=True):
            lowest = ctx.period_lowest.get(days)
            if lowest is None or current.price >= lowest.price:
                continue

            event_type = self.period_event_map.get(days)
            if event_type is None:
                continue

            history = ctx.price_history.get(days, [])
            new_history = [p for p in history if not p.is_used]
            avg_price = None
            change_percent = None
            if new_history:
                avg_price = int(sum(p.price for p in new_history) / len(new_history))
                if avg_price > 0:
                    change_percent = (current.price - avg_price) / avg_price * 100

            logger.info("[PERIOD_LOW_%s] %s: %s円 < %s円", days, ctx.product_id, f"{current.price:,}", f"{lowest.price:,}")
            return self._build_event(
                current,
                event_type=event_type,
                product_id=ctx.product_id,
                store=current.store,
                price=current.price,
                url=current.url,
                previous_price=lowest.price,
                reference_price=avg_price,
                change_percent=change_percent,
                period_days=days,
                recorded_at=now,
            )

        return None

    def _check_price_drop(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        current: PriceRecordT,
        now: datetime,
    ) -> PriceEventT | None:
        history = ctx.price_history.get(7, [])
        new_history = [p for p in history if not p.is_used]
        if len(new_history) < 2:
            return None

        recent_avg = sum(p.price for p in new_history) / len(new_history)
        if recent_avg <= 0:
            return None

        drop_percent = (recent_avg - current.price) / recent_avg * 100
        if drop_percent < self.config.price_drop_threshold_percent:
            return None

        logger.info(
            "[PRICE_DROP] %s: %.1f%%下落 (%s円 → %s円)",
            ctx.product_id,
            drop_percent,
            f"{recent_avg:,.0f}",
            f"{current.price:,}",
        )
        return self._build_event(
            current,
            event_type=self.event_types.PRICE_DROP,
            product_id=ctx.product_id,
            store=current.store,
            price=current.price,
            url=current.url,
            previous_price=int(recent_avg),
            change_percent=-drop_percent,
            recorded_at=now,
        )

    def _check_good_used_deal(
        self,
        product_id: str,
        used: PriceRecordT,
        new_price: int,
        now: datetime,
    ) -> PriceEventT | None:
        if new_price <= 0:
            return None

        ratio = used.price / new_price
        if ratio > self.config.good_used_ratio_max:
            return None

        logger.info("[GOOD_USED_DEAL] %s: 中古%s円 / 新品%s円 = %.1f%%", product_id, f"{used.price:,}", f"{new_price:,}", ratio * 100)
        return self._build_event(
            used,
            event_type=self.event_types.GOOD_USED_DEAL,
            product_id=product_id,
            store=used.store,
            price=used.price,
            url=used.url,
            reference_price=new_price,
            change_percent=ratio * 100,
            recorded_at=now,
        )

    def _check_flea_bargain(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        current: PriceRecordT,
        now: datetime,
    ) -> PriceEventT | None:
        if len(ctx.sold_records) < 3:
            return None

        prices = sorted(record.price for record in ctx.sold_records)
        median_price = prices[len(prices) // 2]
        if median_price <= 0:
            return None

        discount_percent = (median_price - current.price) / median_price * 100
        if discount_percent < self.config.flea_bargain_threshold_percent:
            return None

        logger.info(
            "[FLEA_BARGAIN] %s: %s円 vs 相場%s円 (%.1f%%安)",
            ctx.product_id,
            f"{current.price:,}",
            f"{median_price:,}",
            discount_percent,
        )
        return self._build_event(
            current,
            event_type=self.event_types.FLEA_BARGAIN,
            product_id=ctx.product_id,
            store=current.store,
            price=current.price,
            url=current.url,
            reference_price=median_price,
            change_percent=-discount_percent,
            recorded_at=now,
        )

    def _check_price_recovery(
        self,
        ctx: PriceContext[PriceRecordT, SoldRecordT],
        current: PriceRecordT,
        now: datetime,
    ) -> PriceEventT | None:
        history = ctx.price_history.get(30, [])
        new_history = [p for p in history if not p.is_used]
        if len(new_history) < 5:
            return None

        lowest = min(new_history, key=lambda p: p.price)
        lowest_index = new_history.index(lowest)

        days_since_low = (now - lowest.recorded_at).days
        if days_since_low < self.config.price_recovery_min_days_after_low:
            return None

        prices_after_low = new_history[lowest_index + 1 :]
        if len(prices_after_low) < self.config.price_recovery_consecutive_rises:
            return None

        consecutive_rises = 0
        prev_price = lowest.price
        for price in prices_after_low:
            if price.price > prev_price:
                consecutive_rises += 1
            else:
                consecutive_rises = 0
            prev_price = price.price

        recovery_percent = (current.price - lowest.price) / lowest.price * 100
        is_bottom_rebound = recovery_percent >= self.config.price_recovery_threshold_percent
        is_consecutive_rise = (
            consecutive_rises >= self.config.price_recovery_consecutive_rises
            and recovery_percent >= self.config.price_recovery_consecutive_min_percent
        )
        if not (is_bottom_rebound or is_consecutive_rise):
            return None

        logger.info(
            "[PRICE_RECOVERY] %s: %s円 → %s円 (+%.1f%%, %s回連続上昇)",
            ctx.product_id,
            f"{lowest.price:,}",
            f"{current.price:,}",
            recovery_percent,
            consecutive_rises,
        )
        return self._build_event(
            current,
            event_type=self.event_types.PRICE_RECOVERY,
            product_id=ctx.product_id,
            store=current.store,
            price=current.price,
            url=current.url,
            previous_price=lowest.price,
            change_percent=recovery_percent,
            recorded_at=now,
        )

    def _apply_suppression(self, product_id: str, detected: list[PriceEventT]) -> list[PriceEventT]:
        if not detected:
            return []

        best_new = detected[0]
        if self.event_store.has_recent_similar_price_event(
            product_id,
            getattr(best_new, "store"),
            getattr(best_new, "price"),
            days=self.config.same_price_suppression_days,
            tolerance=self.config.same_price_tolerance,
        ):
            logger.debug("類似価格イベント抑制（14日以内）: %s - %s", getattr(best_new, "event_type").label, product_id)
            return []

        existing = self.event_store.get_recent_event_for_product(
            product_id,
            hours=self.config.suppression_window_hours,
        )
        if existing is None:
            event_id = self.event_store.save_event(best_new)
            logger.info("新規イベント保存: %s - %s (ID: %s)", getattr(best_new, "event_type").label, product_id, event_id)
            return [replace(best_new, id=event_id)]

        if getattr(best_new, "priority") < getattr(existing, "priority"):
            event_id = self.event_store.save_event(best_new)
            existing_id = getattr(existing, "id")
            if existing_id:
                self.event_store.suppress_event(existing_id, event_id)
            logger.info(
                "イベント上書き: %s → %s - %s",
                getattr(existing, "event_type").label,
                getattr(best_new, "event_type").label,
                product_id,
            )
            return [replace(best_new, id=event_id)]

        logger.debug(
            "イベント抑制: %s (既存: %s) - %s",
            getattr(best_new, "event_type").label,
            getattr(existing, "event_type").label,
            product_id,
        )
        return []

    def detect_events(self, product_id: str) -> list[PriceEventT]:
        current_prices = self.price_store.get_current_prices(product_id)
        return self.detect_events_for_product(product_id, current_prices)
