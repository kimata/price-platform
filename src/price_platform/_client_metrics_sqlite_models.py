"""Shared models and helpers for client metrics persistence."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

logger = logging.getLogger(__name__)

DeviceType = Literal["mobile", "desktop"]
MetricName = Literal["ttfb_ms", "dom_interactive_ms", "dom_complete_ms", "load_event_ms"]
WebVitalName = Literal["LCP", "CLS", "INP", "FCP", "TTFB"]
WebVitalRating = Literal["good", "needs-improvement", "poor"]
SocialReferralEventName = Literal["landing", "engaged_30s", "second_page"]

_WEB_VITAL_MAX_VALUES: dict[str, float] = {
    "LCP": 60_000,
    "FCP": 60_000,
    "INP": 30_000,
    "TTFB": 60_000,
    "CLS": 5.0,
}
_CLIENT_PERF_MAX_MS = 120_000

_MOBILE_PATTERN = re.compile(
    r"(android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini|mobile)",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _date_range(date_str: str) -> tuple[str, str]:
    d = date.fromisoformat(date_str)
    next_d = d + timedelta(days=1)
    return f"{d.isoformat()}T00:00:00", f"{next_d.isoformat()}T00:00:00"


def _date_gte(date_str: str) -> str:
    return f"{date_str}T00:00:00"


def _date_lt(date_str: str) -> str:
    return f"{date_str}T00:00:00"


def _filter_web_vital_values(metric_name: str, rows: list[tuple]) -> tuple[list[float], list[str]]:
    max_value = _WEB_VITAL_MAX_VALUES.get(metric_name, 60_000)
    values: list[float] = []
    ratings: list[str] = []
    for row in rows:
        value = row[0]
        if value < 0 or value > max_value:
            continue
        values.append(value)
        ratings.append(row[1])
    return values, ratings


@dataclass(frozen=True)
class ClientPerfRaw:
    device_type: DeviceType
    ttfb_ms: float | None
    dom_interactive_ms: float | None
    dom_complete_ms: float | None
    load_event_ms: float | None
    page_path: str | None
    user_agent: str | None

    @classmethod
    def parse(cls, data: dict) -> ClientPerfRaw | None:
        def _validate_timing(value: float | int | str | None) -> float | None:
            if value is None:
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            if math.isnan(parsed) or math.isinf(parsed) or parsed < 0 or parsed > _CLIENT_PERF_MAX_MS:
                return None
            return parsed

        ttfb = _validate_timing(data.get("ttfb_ms"))
        dom_interactive = _validate_timing(data.get("dom_interactive_ms"))
        dom_complete = _validate_timing(data.get("dom_complete_ms"))
        load_event = _validate_timing(data.get("load_event_ms"))

        if ttfb is None and dom_interactive is None and dom_complete is None and load_event is None:
            logger.debug("Client perf data rejected: all timing metrics invalid or missing")
            return None

        return cls(
            device_type=data.get("device_type", "desktop"),
            ttfb_ms=ttfb,
            dom_interactive_ms=dom_interactive,
            dom_complete_ms=dom_complete,
            load_event_ms=load_event,
            page_path=data.get("page_path"),
            user_agent=data.get("user_agent"),
        )


@dataclass(frozen=True)
class ClientPerfDaily:
    date: str
    device_type: DeviceType
    metric_name: MetricName
    min_value: float
    q1_value: float
    median_value: float
    q3_value: float
    max_value: float
    avg_value: float
    entry_count: int


@dataclass(frozen=True)
class BoxplotData:
    date: str
    device_type: DeviceType
    min_val: float
    q1: float
    median: float
    q3: float
    max_val: float
    avg: float
    count: int


@dataclass(frozen=True)
class WebVitalRaw:
    device_type: DeviceType
    metric_name: WebVitalName
    metric_value: float
    rating: WebVitalRating
    page_path: str | None

    @classmethod
    def parse(cls, data: dict, device_type: DeviceType) -> WebVitalRaw | None:
        name = data.get("name")
        value = data.get("value")
        rating = data.get("rating")
        page_path = data.get("page_path")

        if name not in ("LCP", "CLS", "INP", "FCP", "TTFB"):
            return None
        if value is None or rating is None:
            return None
        if rating not in ("good", "needs-improvement", "poor"):
            return None

        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(float_value) or math.isinf(float_value) or float_value < 0:
            logger.debug("Web vital %s rejected: invalid value %s", name, value)
            return None

        max_value = _WEB_VITAL_MAX_VALUES.get(name, 60_000)
        if float_value > max_value:
            logger.debug("Web vital %s rejected: value %.2f exceeds max %.0f", name, float_value, max_value)
            return None

        return cls(
            device_type=device_type,
            metric_name=name,
            metric_value=float_value,
            rating=rating,
            page_path=page_path,
        )


@dataclass(frozen=True)
class WebVitalDaily:
    date: str
    device_type: DeviceType
    metric_name: WebVitalName
    min_value: float
    q1_value: float
    median_value: float
    q3_value: float
    max_value: float
    avg_value: float
    entry_count: int
    good_count: int
    needs_improvement_count: int
    poor_count: int


@dataclass(frozen=True)
class WebVitalBoxplotData:
    date: str
    device_type: DeviceType
    metric_name: WebVitalName
    min_val: float
    q1: float
    median: float
    q3: float
    max_val: float
    avg: float
    count: int
    good_pct: float
    needs_improvement_pct: float
    poor_pct: float


def detect_device_type(user_agent: str | None) -> DeviceType:
    if user_agent is None:
        return "desktop"
    if _MOBILE_PATTERN.search(user_agent):
        return "mobile"
    return "desktop"


def _clean_text(value: object, *, max_len: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    compact = _WHITESPACE_RE.sub(" ", value).strip()
    if not compact:
        return None
    return compact[:max_len]


@dataclass(frozen=True)
class SocialReferralEventRaw:
    event_name: SocialReferralEventName
    source: str
    medium: str | None
    campaign: str | None
    post_variant: str | None
    post_id: str | None
    social_event: str | None
    session_id: str
    landing_path: str
    page_path: str
    referrer: str | None
    page_depth: int
    device_type: DeviceType
    user_agent: str | None

    @classmethod
    def parse(cls, data: dict, device_type: DeviceType, user_agent: str | None) -> SocialReferralEventRaw | None:
        event_name = data.get("event_name")
        if event_name not in ("landing", "engaged_30s", "second_page"):
            return None

        source = _clean_text(data.get("source"), max_len=32)
        session_id = _clean_text(data.get("session_id"), max_len=64)
        landing_path = _clean_text(data.get("landing_path"), max_len=255)
        page_path = _clean_text(data.get("page_path"), max_len=255)
        if source is None or session_id is None or landing_path is None or page_path is None:
            return None
        if not landing_path.startswith("/") or not page_path.startswith("/"):
            return None

        try:
            page_depth = int(data.get("page_depth", 1))
        except (TypeError, ValueError):
            return None
        if page_depth < 1 or page_depth > 100:
            return None

        return cls(
            event_name=event_name,
            source=source,
            medium=_clean_text(data.get("medium"), max_len=32),
            campaign=_clean_text(data.get("campaign"), max_len=64),
            post_variant=_clean_text(data.get("post_variant"), max_len=32),
            post_id=_clean_text(data.get("post_id"), max_len=64),
            social_event=_clean_text(data.get("social_event"), max_len=32),
            session_id=session_id,
            landing_path=landing_path,
            page_path=page_path,
            referrer=_clean_text(data.get("referrer"), max_len=255),
            page_depth=page_depth,
            device_type=device_type,
            user_agent=user_agent,
        )
