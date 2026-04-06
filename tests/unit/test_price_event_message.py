from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from price_platform.store import PriceEventType, format_event_message, format_event_message_from_event


def test_price_event_type_metadata_is_stable() -> None:
    assert PriceEventType.STATISTICAL_LOW.value == "statistical_low"
    assert PriceEventType.STATISTICAL_LOW.label == "統計的安値"
    assert PriceEventType.STATISTICAL_LOW.priority == 3


def test_format_event_message_for_statistical_low() -> None:
    message = format_event_message(
        "SONY WH-1000XM6",
        event_type_value="statistical_low",
        rarity_tier="HIGH",
    )

    assert "珍しい水準" in message


class _EventType(StrEnum):
    STATISTICAL_LOW = "statistical_low"


@dataclass(frozen=True)
class _Event:
    event_type: _EventType
    previous_price: int | None = None
    reference_price: int | None = None
    change_percent: float | None = None
    period_days: int | None = None
    rarity_tier: str | None = "VERY_HIGH"


def test_format_event_message_from_event_uses_shared_fields() -> None:
    message = format_event_message_from_event(_Event(event_type=_EventType.STATISTICAL_LOW), "EOS R6 Mark II")

    assert "かなり珍しい水準" in message

