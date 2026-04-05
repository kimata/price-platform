"""Suppression logic for detected price events."""

from __future__ import annotations

import logging
from dataclasses import replace

from ._price_event_types import DetectedPriceEventProtocol, PriceEventConfig, PriceEventStoreProtocol

logger = logging.getLogger(__name__)


def _event_label(event: DetectedPriceEventProtocol) -> str:
    return getattr(event.event_type, "label", str(event.event_type))


def apply_event_suppression(
    *,
    event_store: PriceEventStoreProtocol[DetectedPriceEventProtocol],
    product_id: str,
    detected: list[DetectedPriceEventProtocol],
    config: PriceEventConfig,
) -> list[DetectedPriceEventProtocol]:
    if not detected:
        return []

    best_new = detected[0]
    if event_store.has_recent_similar_price_event(
        product_id,
        best_new.store,
        best_new.price,
        days=config.same_price_suppression_days,
        tolerance=config.same_price_tolerance,
    ):
        logger.debug(
            "類似価格イベント抑制（%s日以内）: %s - %s",
            config.same_price_suppression_days,
            _event_label(best_new),
            product_id,
        )
        return []

    existing = event_store.get_recent_event_for_product(product_id, hours=config.suppression_window_hours)
    if existing is None:
        event_id = event_store.save_event(best_new)
        logger.info("新規イベント保存: %s - %s (ID: %s)", _event_label(best_new), product_id, event_id)
        return [replace(best_new, id=event_id)]

    if best_new.priority < existing.priority:
        event_id = event_store.save_event(best_new)
        if existing.id:
            event_store.suppress_event(existing.id, event_id)
        logger.info("イベント上書き: %s → %s - %s", _event_label(existing), _event_label(best_new), product_id)
        return [replace(best_new, id=event_id)]

    logger.debug("イベント抑制: %s (既存: %s) - %s", _event_label(best_new), _event_label(existing), product_id)
    return []
