from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from itertools import combinations

from price_platform.store.fetcher_common import FilterReason

from .scoring import KeywordMatcher, mine_negative_tokens, score_observation_details
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

    for (_project, _product_id), grouped_records in grouped.items():
        admitted_reference = [record for record in grouped_records if record.admitted]
        quarantined_missing = [
            record
            for record in grouped_records
            if not record.admitted and record.reason == FilterReason.MISSING_KEYWORDS.value
        ]
        if not admitted_reference or not quarantined_missing:
            continue

        product_name = grouped_records[0].product_name
        project = grouped_records[0].project
        product_id = grouped_records[0].product_id
        required_keywords = grouped_records[0].required_keywords
        anchor_keywords = grouped_records[0].anchor_keywords
        candidate_keywords = tuple(keyword for keyword in required_keywords if keyword not in anchor_keywords)
        if not candidate_keywords:
            continue

        scored_missing = [
            (
                record,
                score_observation_details(
                    record,
                    admitted_reference=admitted_reference,
                    related_quarantined=quarantined_missing,
                    keyword_matcher=keyword_matcher,
                ),
            )
            for record in quarantined_missing
        ]

        positives = {
            record.listing_url for record, details in scored_missing if details.validity_score >= 0.80
        }
        if len(positives) < 12:
            continue

        best_proposal: KeywordProposal | None = None
        for drop_keywords in _candidate_drop_sets(candidate_keywords):
            rescued = [
                (record, details)
                for record, details in scored_missing
                if _matches_candidate(record, drop_keywords)
            ]
            rescued_positive = [
                record for record, details in rescued if details.validity_score >= 0.80
            ]
            rescued_negative = [
                record for record, details in rescued if details.validity_score < 0.45
            ]
            support = len(rescued_positive) + len(rescued_negative)
            if support < 30:
                continue

            distinct_days = {
                record.captured_at.date().isoformat()
                for record in (*rescued_positive, *rescued_negative)
            }
            if len(distinct_days) < 7:
                continue

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
                continue

            payload = {
                "drop_keywords": list(drop_keywords),
                "anchor_keywords": list(anchor_keywords),
            }
            payload_key = serialize_json_payload(payload)
            if candidate_payloads_out is not None:
                candidate_payloads_out.add(payload_key)
            prior_consecutive_runs = prior_run_payload_counts.get(payload_key, 0)
            consecutive_runs = prior_consecutive_runs + 1
            if consecutive_runs < min_consecutive_runs:
                continue

            score_value = _proposal_score(precision_lcb, recall_gain, support)

            good_records = rescued_positive
            price_suspicious_bad_records = [
                record
                for record, details in rescued
                if details.validity_score < 0.45 and details.price_robust_z >= 2.5
            ]
            ng_tokens: list[str] = []
            if len(price_suspicious_bad_records) >= 5:
                ng_tokens = mine_negative_tokens(
                    bad_records=price_suspicious_bad_records,
                    good_records=good_records,
                    anchor_keywords=anchor_keywords,
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
                "distinct_days": len(distinct_days),
                "consecutive_runs": consecutive_runs,
            }
            window = AnalysisWindow(
                started_at=min(record.captured_at for record in grouped_records),
                ended_at=max(record.captured_at for record in grouped_records),
            )
            proposal = KeywordProposal(
                project=project,
                product_id=product_id,
                product_name=product_name,
                kind=ProposalKind.RELAX_REQUIRED_KEYWORDS,
                payload=payload,
                metrics=metrics,
                evidence=evidence,
                score=score_value,
                analysis_window=window,
                created_at=datetime.now(),
            )
            if best_proposal is None:
                best_proposal = proposal
                continue

            current_key = (
                proposal.metrics["precision_lcb"],
                proposal.metrics["estimated_recall_gain"],
                -len(drop_keywords),
                proposal.metrics["support"],
            )
            best_key = (
                best_proposal.metrics["precision_lcb"],
                best_proposal.metrics["estimated_recall_gain"],
                -len(best_proposal.payload["drop_keywords"]),
                best_proposal.metrics["support"],
            )
            if current_key > best_key:
                best_proposal = proposal

        if best_proposal is None:
            continue
        proposals.append(best_proposal)

        candidate_ng_words = best_proposal.evidence.get("candidate_ng_words", [])
        price_suspicious_negative_urls = best_proposal.evidence.get("price_suspicious_negative_urls", [])
        if candidate_ng_words and len(price_suspicious_negative_urls) >= 5:
            proposals.append(
                replace(
                    best_proposal,
                    kind=ProposalKind.ADD_NG_WORDS,
                    payload={"add_ng_words": list(candidate_ng_words[:5])},
                    score=best_proposal.score - 0.02,
                )
            )

    return proposals
