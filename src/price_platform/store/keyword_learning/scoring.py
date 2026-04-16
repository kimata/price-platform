from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from price_platform.store.fetcher_common import default_keyword_in_title

from .types import ObservationRecord

KeywordMatcher = Callable[[str, str], bool]


@dataclass(frozen=True)
class ObservationScore:
    validity_score: float
    price_robust_z: float


def normalize_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip().upper())
    return normalized.replace("／", "/").replace("・", " ").replace("-", "")


def tokenize_title(title: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^A-Z0-9一-龠ぁ-んァ-ヶ]+", normalize_title(title)) if token)


def trigram_set(title: str) -> set[str]:
    normalized = normalize_title(title)
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def robust_price_outlier(
    *,
    price: int,
    baseline_price: int | None,
    baseline_ratios: list[float],
) -> float:
    if baseline_price is None or baseline_price <= 0 or not baseline_ratios:
        return 0.0
    ratio = math.log(price / baseline_price)
    median_ratio = statistics.median(baseline_ratios)
    deviations = [abs(value - median_ratio) for value in baseline_ratios]
    mad = statistics.median(deviations) if deviations else 0.0
    denom = (1.4826 * mad) + 1e-6
    return min(abs(ratio - median_ratio) / denom, 6.0)


def _mean_top_k(values: list[float], k: int = 3) -> float:
    if not values:
        return 0.0
    top_values = sorted(values, reverse=True)[:k]
    return sum(top_values) / len(top_values)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def score_observation(
    observation: ObservationRecord,
    *,
    admitted_reference: list[ObservationRecord],
    related_quarantined: list[ObservationRecord],
    keyword_matcher=default_keyword_in_title,
) -> float:
    return score_observation_details(
        observation,
        admitted_reference=admitted_reference,
        related_quarantined=related_quarantined,
        keyword_matcher=keyword_matcher,
    ).validity_score


def score_observation_details(
    observation: ObservationRecord,
    *,
    admitted_reference: list[ObservationRecord],
    related_quarantined: list[ObservationRecord],
    keyword_matcher=default_keyword_in_title,
) -> ObservationScore:
    matched_required = len(observation.required_keywords) - len(observation.missing_keywords)
    keyword_coverage = (
        matched_required / len(observation.required_keywords) if observation.required_keywords else 0.0
    )

    if observation.anchor_keywords:
        matched_anchor = sum(
            1 for keyword in observation.anchor_keywords if keyword_matcher(keyword, observation.title_normalized)
        )
        anchor_coverage = matched_anchor / len(observation.anchor_keywords)
    else:
        anchor_coverage = 0.0

    token_scores = [
        jaccard_similarity(set(tokenize_title(observation.listing_title)), set(tokenize_title(record.listing_title)))
        for record in admitted_reference
    ]
    trigram_scores = [
        jaccard_similarity(trigram_set(observation.listing_title), trigram_set(record.listing_title))
        for record in admitted_reference
    ]
    token_jaccard_max = max(token_scores, default=0.0)
    token_jaccard_mean_topk = _mean_top_k(token_scores, k=3)
    trigram_jaccard_max = max(trigram_scores, default=0.0)

    baseline_price = observation.reference_price
    if baseline_price is None and admitted_reference:
        baseline_price = int(statistics.median(record.listing_price for record in admitted_reference))

    baseline_ratios = [
        math.log(record.listing_price / baseline_price)
        for record in admitted_reference
        if baseline_price is not None and baseline_price > 0 and record.listing_price > 0
    ]
    price_robust_z = robust_price_outlier(
        price=observation.listing_price,
        baseline_price=baseline_price,
        baseline_ratios=baseline_ratios,
    )

    similar_quarantine_hits = 0
    other_store_hit = 0
    target_tokens = set(tokenize_title(observation.listing_title))
    target_trigrams = trigram_set(observation.listing_title)
    for record in related_quarantined:
        if record.listing_url == observation.listing_url:
            continue
        token_score = jaccard_similarity(target_tokens, set(tokenize_title(record.listing_title)))
        trigram_score = jaccard_similarity(target_trigrams, trigram_set(record.listing_title))
        if token_score >= 0.8 or trigram_score >= 0.85:
            similar_quarantine_hits += 1
            if record.store_name != observation.store_name:
                other_store_hit = 1

    ng_penalty = 1 if observation.matched_ng_words or observation.matched_partial_item_words else 0
    exclude_product_penalty = 1 if observation.matched_exclude_product_name else 0
    policy_penalty = 1 if observation.reason == "policy_excluded" else 0

    raw_score = (
        2.0 * keyword_coverage
        + 2.5 * anchor_coverage
        + 1.8 * token_jaccard_max
        + 1.2 * token_jaccard_mean_topk
        + 1.4 * trigram_jaccard_max
        + 0.5 * math.log1p(similar_quarantine_hits)
        + 0.4 * other_store_hit
        - 0.9 * price_robust_z
        - 3.0 * ng_penalty
        - 3.5 * exclude_product_penalty
        - 2.0 * policy_penalty
        - 2.2
    )
    return ObservationScore(
        validity_score=_sigmoid(raw_score),
        price_robust_z=price_robust_z,
    )


def mine_negative_tokens(
    *,
    bad_records: list[ObservationRecord],
    good_records: list[ObservationRecord],
    anchor_keywords: tuple[str, ...],
) -> list[str]:
    bad_docs = [set(tokenize_title(record.listing_title)) for record in bad_records]
    good_docs = [set(tokenize_title(record.listing_title)) for record in good_records]
    bad_counts: Counter[str] = Counter(token for tokens in bad_docs for token in tokens)
    good_counts: Counter[str] = Counter(token for tokens in good_docs for token in tokens)
    bad_total = max(len(bad_docs), 1)
    good_total = max(len(good_docs), 1)
    blocked_tokens = {token.upper() for token in anchor_keywords}
    candidates: list[tuple[float, str]] = []

    for token, bad_freq in bad_counts.items():
        if len(token) <= 1 or token.isdigit() or token in blocked_tokens or bad_freq < 5:
            continue
        good_freq = good_counts[token]
        if good_freq > bad_freq * 0.5:
            continue
        alpha = 0.5
        bad_odds = math.log((bad_freq + alpha) / ((bad_total - bad_freq) + alpha))
        good_odds = math.log((good_freq + alpha) / ((good_total - good_freq) + alpha))
        score = bad_odds - good_odds
        if score >= 0.75:
            candidates.append((score, token))

    return [token for _, token in sorted(candidates, reverse=True)]
