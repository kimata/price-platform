from __future__ import annotations

from datetime import date

import price_platform.market_analysis as ma


def _full_stats() -> ma.MarketStats:
    return ma.MarketStats(
        product_label="RF50mm F1.2 L USM",
        period_days=30,
        new=ma.MarketSideStats(
            lowest=280000,
            lowest_store="Amazon",
            period_min=275000,
            period_max=300000,
            period_avg=288000.0,
            month_change_percent=-1.2,
        ),
        used=ma.MarketSideStats(
            lowest=210000,
            lowest_store="メルカリ",
            period_min=205000,
            period_max=245000,
            period_avg=228000.0,
            current_rank=2,
            unique_price_count=8,
            week_change_percent=-1.0,
            month_change_percent=-7.5,
        ),
        sold_count=24,
        store_count=7,
        updated_at=date(2026, 7, 11),
    )


def test_build_market_analysis_full_data() -> None:
    analysis = ma.build_market_analysis(_full_stats())

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    # 相場レンジ
    assert "205,000円〜245,000円" in text
    assert "現在の中古最安値は210,000円(メルカリ)" in text
    assert "8段階の価格のうち安い方から2番目" in text
    # 新品比較 (差額 70,000円 = 25%)
    assert "新品最安値は280,000円(Amazon)" in text
    assert "70,000円(25%)" in text
    # トレンド (中古 -7.5% → 下落局面)
    assert "7.5%下落" in text
    assert "買い時" in text
    # 流通量
    assert "売買成立は24件" in text
    # データ出所
    assert "7店舗" in text
    assert "2026年7月11日" in text
    # サマリー
    assert "中古相場 205,000円〜245,000円" in analysis.summary
    assert "下落" in analysis.summary


def test_returns_none_without_any_price() -> None:
    stats = ma.MarketStats(product_label="X", period_days=30)
    assert ma.build_market_analysis(stats) is None


def test_new_only_product() -> None:
    stats = ma.MarketStats(
        product_label="TD002G",
        period_days=30,
        new=ma.MarketSideStats(lowest=45000, lowest_store="Amazon", month_change_percent=0.5),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    assert "現在の新品最安値は45,000円(Amazon)です。" in text
    assert "ほぼ横ばい" in text
    assert "中古" not in analysis.summary
    # 中古情報が無いので流通量・相場レンジの段落は出ない
    assert "売買成立" not in text


def test_used_above_new_price() -> None:
    stats = ma.MarketStats(
        product_label="X",
        period_days=30,
        new=ma.MarketSideStats(lowest=50000),
        used=ma.MarketSideStats(lowest=52000),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    assert "中古相場が新品最安値" in text
    assert "上回っています" in text


def test_small_price_gap_recommends_new() -> None:
    stats = ma.MarketStats(
        product_label="X",
        period_days=30,
        new=ma.MarketSideStats(lowest=100000),
        used=ma.MarketSideStats(lowest=95000),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    assert "5,000円(5%)" in text
    assert "新品を選ぶ方が無難" in text


def test_large_price_gap_recommends_used() -> None:
    stats = ma.MarketStats(
        product_label="X",
        period_days=30,
        new=ma.MarketSideStats(lowest=100000),
        used=ma.MarketSideStats(lowest=55000),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    assert "45,000円(45%)" in text
    assert "中古のメリット" in text


def test_stable_price_band() -> None:
    stats = ma.MarketStats(
        product_label="X",
        period_days=90,
        used=ma.MarketSideStats(lowest=30000, period_min=30000, period_max=30000),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    text = "".join(analysis.paragraphs)
    assert "直近90日" in text
    assert "30,000円前後で安定" in text


def test_source_paragraph_without_store_count() -> None:
    stats = ma.MarketStats(
        product_label="X",
        period_days=30,
        used=ma.MarketSideStats(lowest=30000),
    )
    analysis = ma.build_market_analysis(stats)

    assert analysis is not None
    assert "複数のオンラインストア・フリマサービス" in analysis.paragraphs[-1]
