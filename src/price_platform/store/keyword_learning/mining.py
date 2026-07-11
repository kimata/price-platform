from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import combinations

from price_platform.store.fetcher_common import FilterReason

from .scoring import KeywordMatcher, ObservationScore, mine_negative_tokens, score_observation_details
from .types import AnalysisWindow, KeywordProposal, ObservationRecord, ProposalKind, serialize_json_payload


def _wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = successes / total
    denominator = 1 + (z * z / total)
    center = phat + (z * z / (2 * total))
    margin = z * math.sqrt((phat * (1 - phat) + (z * z / (4 * total))) / total)
    return max((center - margin) / denominator, 0.0)


def _proposal_score(precision_lcb: float, recall_gain: float, support: int) -> float:
    support_term = min(math.log1p(support) / math.log(31), 1.0)
    return (0.5 * precision_lcb) + (0.3 * recall_gain) + (0.2 * support_term)


def _candidate_drop_sets(candidate_keywords: tuple[str, ...]) -> list[tuple[str, ...]]:
    if len(candidate_keywords) <= 8:
        max_drop = min(3, len(candidate_keywords))
    else:
        max_drop = min(2, len(candidate_keywords))
    candidates: list[tuple[str, ...]] = []
    for drop_size in range(1, max_drop + 1):
        candidates.extend(combinations(candidate_keywords, drop_size))
    return candidates


def _matches_candidate(record: ObservationRecord, drop_keywords: tuple[str, ...]) -> bool:
    drop_set = set(drop_keywords)
    return set(record.missing_keywords).issubset(drop_set)


def analyze_observations(
    records: list[ObservationRecord],
    *,
    prior_run_payload_counts: dict[str, int] | None = None,
    keyword_matcher: KeywordMatcher,
    candidate_payloads_out: set[str] | None = None,
    min_consecutive_runs: int = 2,
) -> list[KeywordProposal]:
    prior_run_payload_counts = prior_run_payload_counts or {}
    grouped: dict[tuple[str, str], list[ObservationRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.project, record.product_id)].append(record)

    proposals: list[KeywordProposal] = []

    for grouped_records in grouped.values():
        group = _collect_group_inputs(grouped_records)
        if group is None:
            continue

        scored_missing = _score_missing_observations(group, keyword_matcher)
        positives = {
            record.listing_url for record, details in scored_missing if details.validity_score >= 0.80
        }
        if len(positives) < 12:
            continue

        best_proposal = _select_best_proposal(
            group,
            scored_missing=scored_missing,
            positives=positives,
            prior_run_payload_counts=prior_run_payload_counts,
            candidate_payloads_out=candidate_payloads_out,
            min_consecutive_runs=min_consecutive_runs,
        )
        if best_proposal is None:
            continue
        proposals.append(best_proposal)

        ng_word_proposal = _derive_ng_word_proposal(best_proposal)
        if ng_word_proposal is not None:
            proposals.append(ng_word_proposal)

    return proposals


@dataclass(frozen=True)
class _GroupInputs:
    """1 製品グループの分析入力。"""

    grouped_records: list[ObservationRecord]
    admitted_reference: list[ObservationRecord]
    quarantined_missing: list[ObservationRecord]
    project: str
    product_id: str
    product_name: str
    anchor_keywords: tuple[str, ...]
    candidate_keywords: tuple[str, ...]


def _collect_group_inputs(grouped_records: list[ObservationRecord]) -> _GroupInputs | None:
    """グループから分析入力を組み立てる。分析対象外なら None。"""
    admitted_reference = [record for record in grouped_records if record.admitted]
    quarantined_missing = [
        record
        for record in grouped_records
        if not record.admitted and record.reason == FilterReason.MISSING_KEYWORDS.value
    ]
    if not admitted_reference or not quarantined_missing:
        return None

    head = grouped_records[0]
    candidate_keywords = tuple(
        keyword for keyword in head.required_keywords if keyword not in head.anchor_keywords
    )
    if not candidate_keywords:
        return None

    return _GroupInputs(
        grouped_records=grouped_records,
        admitted_reference=admitted_reference,
        quarantined_missing=quarantined_missing,
        project=head.project,
        product_id=head.product_id,
        product_name=head.product_name,
        anchor_keywords=tuple(head.anchor_keywords),
        candidate_keywords=candidate_keywords,
    )


def _score_missing_observations(
    group: _GroupInputs, keyword_matcher: KeywordMatcher
) -> list[tuple[ObservationRecord, ObservationScore]]:
    """キーワード欠落で検疫された観測をスコアリングする。"""
    return [
        (
            record,
            score_observation_details(
                record,
                admitted_reference=group.admitted_reference,
                related_quarantined=group.quarantined_missing,
                keyword_matcher=keyword_matcher,
            ),
        )
        for record in group.quarantined_missing
    ]


def _select_best_proposal(
    group: _GroupInputs,
    *,
    scored_missing: list[tuple[ObservationRecord, ObservationScore]],
    positives: set[str],
    prior_run_payload_counts: dict[str, int],
    candidate_payloads_out: set[str] | None,
    min_consecutive_runs: int,
) -> KeywordProposal | None:
    """drop 候補集合を評価し、最良の提案を選ぶ。"""
    best_proposal: KeywordProposal | None = None
    for drop_keywords in _candidate_drop_sets(group.candidate_keywords):
        proposal = _evaluate_drop_candidate(
            group,
            drop_keywords=drop_keywords,
            scored_missing=scored_missing,
            positives=positives,
            prior_run_payload_counts=prior_run_payload_counts,
            candidate_payloads_out=candidate_payloads_out,
            min_consecutive_runs=min_consecutive_runs,
        )
        if proposal is None:
            continue
        if best_proposal is None or _proposal_sort_key(proposal) > _proposal_sort_key(best_proposal):
            best_proposal = proposal
    return best_proposal


def _proposal_sort_key(proposal: KeywordProposal) -> tuple[float, float, int, int]:
    return (
        proposal.metrics["precision_lcb"],
        proposal.metrics["estimated_recall_gain"],
        -len(proposal.payload["drop_keywords"]),
        proposal.metrics["support"],
    )


def _evaluate_drop_candidate(
    group: _GroupInputs,
    *,
    drop_keywords: tuple[str, ...],
    scored_missing: list[tuple[ObservationRecord, ObservationScore]],
    positives: set[str],
    prior_run_payload_counts: dict[str, int],
    candidate_payloads_out: set[str] | None,
    min_consecutive_runs: int,
) -> KeywordProposal | None:
    """1 つの drop 候補を品質基準で評価し、合格すれば提案を構築する。"""
    rescued = [
        (record, details) for record, details in scored_missing if _matches_candidate(record, drop_keywords)
    ]
    rescued_positive = [record for record, details in rescued if details.validity_score >= 0.80]
    rescued_negative = [record for record, details in rescued if details.validity_score < 0.45]
    support = len(rescued_positive) + len(rescued_negative)
    if support < 30:
        return None

    distinct_days = {
        record.captured_at.date().isoformat() for record in (*rescued_positive, *rescued_negative)
    }
    if len(distinct_days) < 7:
        return None

    alpha = 2
    beta = 5
    smoothed_precision = (len(rescued_positive) + alpha) / (support + alpha + beta)
    precision_lcb = _wilson_lower_bound(len(rescued_positive), support)
    recall_gain = len(rescued_positive) / max(len(positives), 1)
    negative_ratio = len(rescued_negative) / support
    if (
        smoothed_precision < 0.82
        or precision_lcb < 0.70
        or recall_gain < 0.05
        or negative_ratio > 0.12
    ):
        return None

    payload = {
        "drop_keywords": list(drop_keywords),
        "anchor_keywords": list(group.anchor_keywords),
    }
    payload_key = serialize_json_payload(payload)
    if candidate_payloads_out is not None:
        candidate_payloads_out.add(payload_key)
    consecutive_runs = prior_run_payload_counts.get(payload_key, 0) + 1
    if consecutive_runs < min_consecutive_runs:
        return None

    return _build_proposal(
        group,
        payload=payload,
        rescued=rescued,
        rescued_positive=rescued_positive,
        rescued_negative=rescued_negative,
        support=support,
        smoothed_precision=smoothed_precision,
        precision_lcb=precision_lcb,
        recall_gain=recall_gain,
        distinct_days=len(distinct_days),
        consecutive_runs=consecutive_runs,
    )


def _build_proposal(
    group: _GroupInputs,
    *,
    payload: dict,
    rescued: list[tuple[ObservationRecord, ObservationScore]],
    rescued_positive: list[ObservationRecord],
    rescued_negative: list[ObservationRecord],
    support: int,
    smoothed_precision: float,
    precision_lcb: float,
    recall_gain: float,
    distinct_days: int,
    consecutive_runs: int,
) -> KeywordProposal:
    """評価済みの候補から KeywordProposal を構築する。"""
    price_suspicious_bad_records = [
        record
        for record, details in rescued
        if details.validity_score < 0.45 and details.price_robust_z >= 2.5
    ]
    ng_tokens: list[str] = []
    if len(price_suspicious_bad_records) >= 5:
        ng_tokens = mine_negative_tokens(
            bad_records=price_suspicious_bad_records,
            good_records=rescued_positive,
            anchor_keywords=group.anchor_keywords,
        )
    evidence = {
        "rescued_positive_urls": [record.listing_url for record in rescued_positive[:10]],
        "rescued_negative_urls": [record.listing_url for record in rescued_negative[:10]],
        "price_suspicious_negative_urls": [
            record.listing_url for record in price_suspicious_bad_records[:10]
        ],
        "candidate_ng_words": ng_tokens[:10],
    }
    metrics = {
        "support": support,
        "rescued_positive": len(rescued_positive),
        "rescued_negative": len(rescued_negative),
        "smoothed_precision": round(smoothed_precision, 4),
        "precision_lcb": round(precision_lcb, 4),
        "estimated_recall_gain": round(recall_gain, 4),
        "distinct_days": distinct_days,
        "consecutive_runs": consecutive_runs,
    }
    window = AnalysisWindow(
        started_at=min(record.captured_at for record in group.grouped_records),
        ended_at=max(record.captured_at for record in group.grouped_records),
    )
    return KeywordProposal(
        project=group.project,
        product_id=group.product_id,
        product_name=group.product_name,
        kind=ProposalKind.RELAX_REQUIRED_KEYWORDS,
        payload=payload,
        metrics=metrics,
        evidence=evidence,
        score=_proposal_score(precision_lcb, recall_gain, support),
        analysis_window=window,
        created_at=datetime.now(),
    )


def _derive_ng_word_proposal(best_proposal: KeywordProposal) -> KeywordProposal | None:
    """採用提案の証跡から NG ワード追加の派生提案を作る。"""
    candidate_ng_words = best_proposal.evidence.get("candidate_ng_words", [])
    price_suspicious_negative_urls = best_proposal.evidence.get("price_suspicious_negative_urls", [])
    if not candidate_ng_words or len(price_suspicious_negative_urls) < 5:
        return None
    return replace(
        best_proposal,
        kind=ProposalKind.ADD_NG_WORDS,
        payload={"add_ng_words": list(candidate_ng_words[:5])},
        score=best_proposal.score - 0.02,
    )
