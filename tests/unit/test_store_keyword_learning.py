from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

import pytest

import price_platform.store as store_module
import price_platform.store.keyword_learning.store as keyword_learning_store_module
from price_platform.platform import clock
from price_platform.platform import notify as platform_notify
from price_platform.store.fetcher_common import (
    DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    FilterReason,
    ProductNameRule,
    default_keyword_in_title,
    filter_by_product_name_match,
)
from price_platform.store.keyword_learning.cli import main as keyword_learning_main
from price_platform.store.keyword_learning.mining import analyze_observations
from price_platform.store.keyword_learning.store import (
    open_keyword_learning_store,
    record_filter_result_safely,
)
from price_platform.store.keyword_learning.types import FilterObservationContext


@dataclass(frozen=True)
class DummyListing:
    price: int
    url: str
    title: str


def test_default_matching_policy_does_not_exclude_generic_accessory_titles_without_opt_in() -> None:
    prices = [
        DummyListing(price=34000, url="https://example.com/body", title="Sony WH-1000XM5 ブラック"),
        DummyListing(price=3500, url="https://example.com/case", title="Sony WH-1000XM5用ケース"),
    ]
    rule = ProductNameRule(
        required_keywords=("WH-1000XM5",),
        flea_market_ng_words=(),
        condition_ng_words=(),
    )

    result = filter_by_product_name_match(
        prices,
        "WH-1000XM5",
        "test",
        rule=rule,
        matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    )

    assert {listing.url for listing in result.admitted} == {
        "https://example.com/body",
        "https://example.com/case",
    }


def test_product_name_filter_config_alias_is_not_exported() -> None:
    with pytest.raises(AttributeError):
        _ = store_module.ProductNameFilterConfig


def test_default_keyword_matcher_respects_boundaries_for_anchor_keywords() -> None:
    assert default_keyword_in_title("RF", "CANON RF 50MM") is True
    assert default_keyword_in_title("RF", "DRAFT ADAPTER") is False


def test_opt_in_rule_excludes_yo_and_empty_box_titles() -> None:
    prices = [
        DummyListing(price=55000, url="https://example.com/body", title="Makita TD002G 本体"),
        DummyListing(price=2000, url="https://example.com/part", title="TD002G用ビット"),
        DummyListing(price=500, url="https://example.com/box", title="TD002G 空箱"),
    ]
    rule = ProductNameRule(
        required_keywords=("TD002G",),
        exclude_yo_titles=True,
        exclude_empty_box_titles=True,
    )

    result = filter_by_product_name_match(
        prices,
        "TD002G",
        "test",
        rule=rule,
        matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    )

    assert [listing.url for listing in result.admitted] == ["https://example.com/body"]
    excluded_reasons = {
        decision.listing.url: decision.reason for decision in result.decisions if not decision.admitted
    }
    assert excluded_reasons["https://example.com/part"] is FilterReason.POLICY_EXCLUDED
    assert excluded_reasons["https://example.com/box"] is FilterReason.POLICY_EXCLUDED


def test_keyword_learning_store_records_observations_and_generates_proposals(tmp_path) -> None:
    store = open_keyword_learning_store(tmp_path / "keyword_learning.db")
    now = clock.now()

    reference_prices = [
        DummyListing(
            price=100000,
            url=f"https://example.com/admit-{index}",
            title="Canon RF50mm F1.2 USM body",
        )
        for index in range(10)
    ]
    admitted_rule = ProductNameRule(
        required_keywords=("RF50MM", "F1.2", "USM"),
        anchor_keywords=("RF50MM", "F1.2"),
        flea_market_ng_words=(),
        condition_ng_words=(),
    )
    admitted_result = filter_by_product_name_match(
        reference_prices,
        "RF50mm F1.2 USM",
        "mercari",
        rule=admitted_rule,
        matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    )
    store.record_filter_result(
        context=FilterObservationContext(
            project="lens-fleama",
            product_id="rf50mm-f12",
            product_name="RF50mm F1.2 USM",
            store_name="mercari",
            reference_price=120000,
            captured_at=now,
        ),
        result=admitted_result,
        title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
    )

    for day in range(35):
        missing_prices = [
            DummyListing(
                price=98000,
                url=f"https://example.com/missing-{day}",
                title="Canon RF50mm F1.2 body",
            )
        ]
        missing_result = filter_by_product_name_match(
            missing_prices,
            "RF50mm F1.2 USM",
            "mercari",
            rule=admitted_rule,
            matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
        )
        store.record_filter_result(
            context=FilterObservationContext(
                project="lens-fleama",
                product_id="rf50mm-f12",
                product_name="RF50mm F1.2 USM",
                store_name="mercari",
                reference_price=120000,
                captured_at=now + timedelta(days=day),
            ),
            result=missing_result,
            title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
        )

    records = store.list_observations(project="lens-fleama", product_id="rf50mm-f12")
    no_proposals = analyze_observations(
        records,
        prior_run_payload_counts={},
        keyword_matcher=default_keyword_in_title,
    )

    assert records
    assert any(not record.admitted for record in records)
    assert no_proposals == []

    prior_payload_counts = {
        json.dumps(
            {"anchor_keywords": ["RF50MM", "F1.2"], "drop_keywords": ["USM"]},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ): 1
    }
    proposals = analyze_observations(
        records,
        prior_run_payload_counts=prior_payload_counts,
        keyword_matcher=default_keyword_in_title,
    )

    assert proposals
    assert proposals[0].kind.value == "relax_required_keywords"
    assert proposals[0].metrics["consecutive_runs"] == 2


def test_cli_analyze_generates_proposal_on_second_run(tmp_path) -> None:
    store = open_keyword_learning_store(tmp_path / "keyword_learning.db")
    now = clock.now()
    admitted_rule = ProductNameRule(
        required_keywords=("RF50MM", "F1.2", "USM"),
        anchor_keywords=("RF50MM", "F1.2"),
    )

    admitted_prices = [
        DummyListing(
            price=100000,
            url=f"https://example.com/admit-{index}",
            title="Canon RF50mm F1.2 USM body",
        )
        for index in range(10)
    ]
    admitted_result = filter_by_product_name_match(
        admitted_prices,
        "RF50mm F1.2 USM",
        "mercari",
        rule=admitted_rule,
        matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    )
    store.record_filter_result(
        context=FilterObservationContext(
            project="lens-fleama",
            product_id="rf50mm-f12",
            product_name="RF50mm F1.2 USM",
            store_name="mercari",
            reference_price=120000,
            captured_at=now,
        ),
        result=admitted_result,
        title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
    )

    for day in range(35):
        missing_result = filter_by_product_name_match(
            [
                DummyListing(
                    price=98000,
                    url=f"https://example.com/missing-{day}",
                    title="Canon RF50mm F1.2 body",
                )
            ],
            "RF50mm F1.2 USM",
            "mercari",
            rule=admitted_rule,
            matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
        )
        store.record_filter_result(
            context=FilterObservationContext(
                project="lens-fleama",
                product_id="rf50mm-f12",
                product_name="RF50mm F1.2 USM",
                store_name="mercari",
                reference_price=120000,
                captured_at=now + timedelta(days=day),
            ),
            result=missing_result,
            title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
        )

    db_path = tmp_path / "keyword_learning.db"
    keyword_learning_main(["analyze", "--db", str(db_path), "--project", "lens-fleama"])
    assert store.list_proposals(project="lens-fleama") == []

    keyword_learning_main(["analyze", "--db", str(db_path), "--project", "lens-fleama"])
    proposals = store.list_proposals(project="lens-fleama")

    assert proposals
    assert proposals[0].metrics["consecutive_runs"] >= 2


def test_prior_run_payload_counts_skips_empty_runs(tmp_path) -> None:
    store = open_keyword_learning_store(tmp_path / "keyword_learning.db")
    now = clock.now()
    payload = json.dumps(
        {"anchor_keywords": ["RF50MM", "F1.2"], "drop_keywords": ["USM"]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    store.record_analysis_run(
        project="lens-fleama",
        started_at=now - timedelta(days=3),
        observation_count=10,
        proposal_count=1,
        candidate_payloads={payload},
    )
    store.record_analysis_run(
        project="lens-fleama",
        started_at=now - timedelta(days=2),
        observation_count=10,
        proposal_count=0,
        candidate_payloads=set(),
    )
    store.record_analysis_run(
        project="lens-fleama",
        started_at=now - timedelta(days=1),
        observation_count=10,
        proposal_count=1,
        candidate_payloads={payload},
    )

    counts = store.prior_run_payload_counts(
        project="lens-fleama",
        before_started_at=now,
    )

    assert counts[payload] == 2


def test_record_analysis_run_deduplicates_same_started_at(tmp_path) -> None:
    store = open_keyword_learning_store(tmp_path / "keyword_learning.db")
    now = clock.now()
    first_payload = json.dumps(
        {"anchor_keywords": ["RF50MM", "F1.2"], "drop_keywords": ["USM"]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    second_payload = json.dumps(
        {"anchor_keywords": ["RF50MM", "F1.2"], "drop_keywords": ["STM"]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    store.record_analysis_run(
        project="lens-fleama",
        started_at=now,
        observation_count=10,
        proposal_count=1,
        candidate_payloads={first_payload},
    )
    store.record_analysis_run(
        project="lens-fleama",
        started_at=now,
        observation_count=10,
        proposal_count=1,
        candidate_payloads={second_payload},
    )

    counts = store.prior_run_payload_counts(
        project="lens-fleama",
        before_started_at=now,
    )

    assert first_payload not in counts
    assert counts[second_payload] == 1


def _make_observation_inputs():
    prices = [
        DummyListing(price=100000, url="https://example.com/a", title="Canon RF50mm F1.2 USM body"),
    ]
    rule = ProductNameRule(
        required_keywords=("RF50MM",),
        flea_market_ng_words=(),
        condition_ng_words=(),
    )
    result = filter_by_product_name_match(
        prices,
        "RF50mm F1.2 USM",
        "mercari",
        rule=rule,
        matching_policy=DEFAULT_PRODUCT_NAME_MATCHING_POLICY,
    )
    context = FilterObservationContext(
        project="lens-fleama",
        product_id="rf50mm-f12",
        product_name="RF50mm F1.2 USM",
        store_name="mercari",
        reference_price=120000,
        captured_at=clock.now(),
    )
    return context, result


def test_record_filter_result_safely_records_on_healthy_db(tmp_path) -> None:
    db_path = tmp_path / "keyword_learning.db"
    context, result = _make_observation_inputs()

    ok = record_filter_result_safely(
        db_path,
        context=context,
        result=result,
        title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
    )

    assert ok is True
    store = open_keyword_learning_store(db_path)
    assert len(store.list_observations(project="lens-fleama")) == 1


def test_record_filter_result_safely_survives_corrupted_db(tmp_path, monkeypatch) -> None:
    """DB 破損時に例外を伝播させず False を返し、Slack 通知を行う。

    学習 DB の破損がスクレイプ結果全体を失敗扱いにしてしまう障害の再発防止。
    """
    db_path = tmp_path / "keyword_learning.db"
    # SQLite ヘッダだけ正しく、中身が壊れたファイルを作る
    db_path.write_bytes(b"SQLite format 3\x00" + b"\xde\xad\xbe\xef" * 1024)

    notified: list[tuple[str, str]] = []
    monkeypatch.setattr(
        keyword_learning_store_module.platform_notify,
        "error",
        lambda _config, title, message: notified.append((title, message)),
    )

    context, result = _make_observation_inputs()
    ok = record_filter_result_safely(
        db_path,
        context=context,
        result=result,
        title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
        slack_config=platform_notify.empty_slack_config(),  # 通知パスに入ることの確認用（error はモック済み）
    )

    assert ok is False
    assert len(notified) == 1
    assert "lens-fleama" in notified[0][0]


def test_record_filter_result_safely_skips_notify_without_slack_config(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "keyword_learning.db"
    db_path.write_bytes(b"SQLite format 3\x00" + b"\xde\xad\xbe\xef" * 1024)

    notified: list[str] = []
    monkeypatch.setattr(
        keyword_learning_store_module.platform_notify,
        "error",
        lambda _config, title, _message: notified.append(title),
    )

    context, result = _make_observation_inputs()
    ok = record_filter_result_safely(
        db_path,
        context=context,
        result=result,
        title_normalizer=DEFAULT_PRODUCT_NAME_MATCHING_POLICY.normalize_title,
    )

    assert ok is False
    assert notified == []
