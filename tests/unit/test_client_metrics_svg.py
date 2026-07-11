"""client metrics SVG 生成と四分位計算のテスト (B6/B9/B21/R2 回帰)。"""

from __future__ import annotations

from price_platform.metrics.client.models import BoxplotData
from price_platform.metrics.client.quartiles import compute_quartiles
from price_platform.metrics.render.boxplot_svg import generate_boxplot_svg


def _boxplot(value: float = 100.0) -> BoxplotData:
    return BoxplotData(
        date="2026-07-11",
        device_type="mobile",
        min_val=value,
        q1=value,
        median=value,
        q3=value,
        max_val=value,
        avg=value,
        count=3,
    )


def test_compute_quartiles_basic() -> None:
    stats = compute_quartiles([1, 2, 3, 4, 5, 6, 7, 8])

    assert stats is not None
    assert stats.min_val == 1
    assert stats.max_val == 8
    assert stats.median == 4.5
    assert stats.q1 == 3  # sorted[8 // 4]
    assert stats.q3 == 7  # sorted[(3 * 8) // 4]
    assert stats.count == 8


def test_compute_quartiles_empty_returns_none() -> None:
    assert compute_quartiles([]) is None


def test_boxplot_svg_escapes_title() -> None:
    """B9 回帰: title が SVG にそのまま埋め込まれない."""
    svg = generate_boxplot_svg((_boxplot(),), '<script>alert("x")</script>')

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_boxplot_svg_escapes_title_in_empty_chart() -> None:
    svg = generate_boxplot_svg((), "<svg onload=x>")

    assert "<svg onload=x>" not in svg


def test_boxplot_svg_handles_all_zero_values() -> None:
    """B21 回帰: 全値 0 (ttfb 0ms は有効値) でもゼロ除算しない."""
    svg = generate_boxplot_svg((_boxplot(0.0),), "TTFB")

    assert "<svg" in svg


def test_boxplot_svg_cache_is_bounded() -> None:
    """B6 回帰: キャッシュが上限付き (無制限の functools.cache でない)."""
    cache_info = generate_boxplot_svg.cache_info()

    assert cache_info.maxsize is not None
