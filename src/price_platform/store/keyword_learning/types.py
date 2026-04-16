from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProposalKind(StrEnum):
    RELAX_REQUIRED_KEYWORDS = "relax_required_keywords"
    ADD_NG_WORDS = "add_ng_words"
    ADD_EXCLUDE_PRODUCT_NAMES = "add_exclude_product_names"
    NO_CHANGE = "no_change"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def serialize_json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class FilterObservationContext:
    project: str
    product_id: str
    product_name: str
    store_name: str
    reference_price: int | None
    captured_at: datetime


@dataclass(frozen=True)
class ObservationRecord:
    project: str
    product_id: str
    product_name: str
    store_name: str
    listing_url: str
    listing_title: str
    listing_price: int
    admitted: bool
    reason: str | None
    missing_keywords: tuple[str, ...]
    matched_ng_words: tuple[str, ...]
    matched_partial_item_words: tuple[str, ...]
    matched_parts_words: tuple[str, ...]
    matched_exclude_product_name: str | None
    required_keywords: tuple[str, ...]
    anchor_keywords: tuple[str, ...]
    exclude_product_names: tuple[str, ...]
    reference_price: int | None
    title_normalized: str
    captured_at: datetime


@dataclass(frozen=True)
class AnalysisWindow:
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class KeywordProposal:
    project: str
    product_id: str
    product_name: str
    kind: ProposalKind
    payload: dict[str, Any]
    metrics: dict[str, float | int]
    evidence: dict[str, Any]
    score: float
    analysis_window: AnalysisWindow = field(default_factory=AnalysisWindow)
    status: ProposalStatus = ProposalStatus.PENDING
    proposal_id: int | None = None
    reviewer: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None
