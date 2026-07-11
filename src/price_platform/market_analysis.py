"""相場分析テキストの生成。

各アプリケーションが自前収集した価格データの集計値から、製品詳細ページに
掲載する「相場分析」の日本語文章を機械的に生成する。他サイトには存在しない
独自データ (フリマ実売・複数ストアの価格履歴) を編集コンテンツ化することが目的。

生成ロジックは純粋関数であり、DB やストアには依存しない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# トレンド判定のしきい値 (%)
_TREND_THRESHOLD_PERCENT = 5.0
# 週次変動を言及するしきい値 (%)
_WEEK_CHANGE_MENTION_PERCENT = 3.0
# 新品との差額の判定しきい値 (%)
_DIFF_LARGE_PERCENT = 40.0
_DIFF_SMALL_PERCENT = 15.0
# 流通量の判定しきい値 (件)
_SOLD_MANY = 20
_SOLD_SOME = 5


@dataclass(frozen=True)
class MarketSideStats:
    """新品または中古の一方の相場集計値。"""

    lowest: int | None = None
    lowest_store: str | None = None
    period_min: int | None = None
    period_max: int | None = None
    period_avg: float | None = None
    current_rank: int | None = None
    unique_price_count: int = 0
    week_change_percent: float | None = None
    month_change_percent: float | None = None


@dataclass(frozen=True)
class MarketStats:
    """相場分析の入力となる集計値。"""

    product_label: str
    period_days: int
    new: MarketSideStats = field(default_factory=MarketSideStats)
    used: MarketSideStats = field(default_factory=MarketSideStats)
    sold_count: int = 0
    store_count: int | None = None
    updated_at: date | datetime | None = None


@dataclass(frozen=True)
class MarketAnalysis:
    """生成された相場分析。"""

    summary: str
    paragraphs: tuple[str, ...]


def _yen(value: int | float) -> str:
    return f"{round(value):,}円"


def _percent(value: float) -> str:
    rounded = round(abs(value), 1)
    if rounded == int(rounded):
        return f"{int(rounded)}%"
    return f"{rounded}%"


def _format_date(value: date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.year}年{value.month}月{value.day}日"


def _used_range_paragraph(stats: MarketStats) -> str | None:
    used = stats.used
    if used.lowest is None:
        return None

    sentences: list[str] = []
    if used.period_min is not None and used.period_max is not None:
        if used.period_min == used.period_max:
            sentences.append(
                f"直近{stats.period_days}日の中古・フリマ相場は{_yen(used.period_min)}前後で安定しています。"
            )
        else:
            avg_part = f"(平均 {_yen(used.period_avg)})" if used.period_avg is not None else ""
            sentences.append(
                f"直近{stats.period_days}日の中古・フリマ相場は"
                f"{_yen(used.period_min)}〜{_yen(used.period_max)}{avg_part}で推移しています。"
            )

    store_part = f"({used.lowest_store})" if used.lowest_store else ""
    sentences.append(f"現在の中古最安値は{_yen(used.lowest)}{store_part}です。")

    if used.current_rank is not None and used.unique_price_count >= 3:
        if used.current_rank == 1:
            sentences.append("これは期間内に観測した価格の中で最も安い水準です。")
        else:
            sentences.append(
                f"これは期間内に観測した{used.unique_price_count}段階の価格のうち"
                f"安い方から{used.current_rank}番目の水準です。"
            )

    return "".join(sentences)


def _new_comparison_paragraph(stats: MarketStats) -> str | None:
    new = stats.new
    used = stats.used
    if new.lowest is None:
        return None

    store_part = f"({new.lowest_store})" if new.lowest_store else ""
    new_part = f"新品最安値は{_yen(new.lowest)}{store_part}"

    if used.lowest is None:
        return f"現在の{new_part}です。"

    diff = new.lowest - used.lowest
    if diff <= 0:
        return (
            f"現在は中古相場が{new_part.replace('新品最安値は', '新品最安値 ')}を上回っています。"
            "急ぎでなければ、新品の値下がりやセールを待つ方が得になる可能性があります。"
        )

    pct = diff / new.lowest * 100
    base = f"{new_part}で、中古との差額は{_yen(diff)}({_percent(pct)})です。"
    if pct >= _DIFF_LARGE_PERCENT:
        advice = "価格差が大きいため、状態の良い個体を選べれば中古のメリットが十分にある水準です。"
    elif pct >= _DIFF_SMALL_PERCENT:
        advice = "保証や初期不良対応を重視するなら新品、価格を優先するなら中古が候補になる価格差です。"
    else:
        advice = "価格差が小さいため、保証の付く新品を選ぶ方が無難な水準です。"
    return base + advice


def _trend_paragraph(stats: MarketStats) -> str | None:
    side = stats.used if stats.used.month_change_percent is not None else stats.new
    label = "中古相場" if side is stats.used else "新品価格"
    month = side.month_change_percent
    if month is None:
        return None

    if month <= -_TREND_THRESHOLD_PERCENT:
        sentence = (
            f"{label}は直近1ヶ月で{_percent(month)}下落しており、値下がり局面です。"
            "相場が下がった今は、買い時に近い水準と言えます。"
        )
    elif month >= _TREND_THRESHOLD_PERCENT:
        sentence = (
            f"{label}は直近1ヶ月で{_percent(month)}上昇しています。"
            "相場が強含んでいるため、購入を決めているなら早めの確保が無難です。"
        )
    else:
        sign = "-" if month < 0 else "+"
        sentence = f"{label}は直近1ヶ月でほぼ横ばい({sign}{_percent(month)})で、急な値動きは見られません。"

    week = side.week_change_percent
    if week is not None and abs(week) >= _WEEK_CHANGE_MENTION_PERCENT:
        direction = "下落" if week < 0 else "上昇"
        sentence += f"直近1週間では{_percent(week)}{direction}しています。"

    return sentence


def _liquidity_paragraph(stats: MarketStats) -> str | None:
    count = stats.sold_count
    if count <= 0:
        return None
    if count >= _SOLD_MANY:
        return (
            f"当サイトが観測したフリマでの売買成立は{count}件と流通量が多く、"
            "複数の出品を比較しながら選びやすい製品です。"
        )
    if count >= _SOLD_SOME:
        return (
            f"フリマでの売買成立を{count}件確認しています。"
            "出品は定期的にあるため、相場を見ながら状態の良い個体を待つ買い方ができます。"
        )
    return (
        f"フリマでの売買成立は{count}件と流通量が少なめです。"
        "希望の条件に合う出品が出たら、早めに判断することをおすすめします。"
    )


def _source_paragraph(stats: MarketStats) -> str:
    if stats.store_count is not None and stats.store_count > 0:
        source = f"{stats.store_count}店舗"
    else:
        source = "複数のオンラインストア・フリマサービス"
    updated_part = f"(最終更新: {_format_date(stats.updated_at)})" if stats.updated_at else ""
    return (
        f"本分析は、当サイトが{source}から毎日自動収集している"
        f"{stats.product_label}の価格データに基づいて生成しています{updated_part}。"
        "中古品の状態は個体差が大きいため、購入前に必ず出品ページの説明をご確認ください。"
    )


def _build_summary(stats: MarketStats) -> str:
    parts: list[str] = []
    used = stats.used
    if used.period_min is not None and used.period_max is not None and used.period_min != used.period_max:
        parts.append(f"中古相場 {_yen(used.period_min)}〜{_yen(used.period_max)}")
    elif used.lowest is not None:
        parts.append(f"中古最安 {_yen(used.lowest)}")
    if stats.new.lowest is not None:
        parts.append(f"新品最安 {_yen(stats.new.lowest)}")
    month = used.month_change_percent
    if month is None:
        month = stats.new.month_change_percent
    if month is not None:
        if month <= -_TREND_THRESHOLD_PERCENT:
            parts.append(f"1ヶ月で{_percent(month)}下落")
        elif month >= _TREND_THRESHOLD_PERCENT:
            parts.append(f"1ヶ月で{_percent(month)}上昇")
        else:
            parts.append("直近1ヶ月は横ばい")
    return "・".join(parts)


def build_market_analysis(stats: MarketStats) -> MarketAnalysis | None:
    """集計値から相場分析を生成する。

    新品・中古とも価格情報が無い場合は None を返す (セクション非表示)。
    """
    if stats.new.lowest is None and stats.used.lowest is None:
        return None

    paragraphs = [
        paragraph
        for paragraph in (
            _used_range_paragraph(stats),
            _new_comparison_paragraph(stats),
            _trend_paragraph(stats),
            _liquidity_paragraph(stats),
            _source_paragraph(stats),
        )
        if paragraph is not None
    ]

    return MarketAnalysis(summary=_build_summary(stats), paragraphs=tuple(paragraphs))
