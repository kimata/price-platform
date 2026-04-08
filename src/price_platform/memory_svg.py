"""SVG rendering helpers for runtime memory charts."""

from __future__ import annotations

import collections.abc
from datetime import datetime
from xml.sax.saxutils import escape

from .managers.pod_memory_tracker import MemorySeriesSnapshot


def generate_memory_usage_svg(
    snapshot: MemorySeriesSnapshot,
    *,
    width: int = 960,
    height: int = 360,
) -> str:
    margin_left = 64
    margin_right = 24
    margin_top = 24
    margin_bottom = 48
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom

    samples = snapshot.samples
    if not samples:
        return _empty_svg(width=width, height=height, message="No memory samples")

    timestamps = [sample.timestamp for sample in samples]
    x_start = snapshot.started_at or timestamps[0]
    x_end = timestamps[-1]
    if x_end <= x_start:
        x_end = x_start

    values_mib = [
        sample.pod_memory_bytes / (1024 * 1024)
        for sample in samples
        if sample.pod_memory_bytes is not None
    ]
    values_mib.extend(
        sample.selenium_memory_bytes / (1024 * 1024)
        for sample in samples
        if sample.selenium_memory_bytes is not None
    )
    if not values_mib:
        return _empty_svg(width=width, height=height, message="No measurable memory data")

    y_max = max(values_mib)
    y_max = max(y_max * 1.1, 64.0)

    def x_pos(timestamp: datetime) -> float:
        span = max((x_end - x_start).total_seconds(), 1.0)
        offset = max((timestamp - x_start).total_seconds(), 0.0)
        return margin_left + (offset / span) * chart_width

    def y_pos(value_mib: float) -> float:
        return margin_top + chart_height - (value_mib / y_max) * chart_height

    pod_path = _build_line_path(
        (
            (x_pos(sample.timestamp), y_pos(sample.pod_memory_bytes / (1024 * 1024)))
            for sample in samples
            if sample.pod_memory_bytes is not None
        )
    )
    selenium_path = _build_line_path(
        (
            (x_pos(sample.timestamp), y_pos(sample.selenium_memory_bytes / (1024 * 1024)))
            for sample in samples
            if sample.selenium_memory_bytes is not None
        )
    )

    y_ticks = []
    for index in range(5):
        value_mib = y_max * index / 4
        y = y_pos(value_mib)
        y_ticks.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" x2="{margin_left + chart_width}" y2="{y:.1f}" '
            'stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            'font-size="12" fill="#475569">'
            f"{value_mib:.0f} MiB</text>"
        )

    x_ticks = []
    tick_count = min(5, len(samples))
    char_width_est = 7.2
    min_gap = 8
    prev_right_edge = -float("inf")

    for index in range(tick_count):
        sample = samples[round(index * (len(samples) - 1) / max(tick_count - 1, 1))]
        x = x_pos(sample.timestamp)
        label = _format_tick(sample.timestamp)
        label_width = len(label) * char_width_est

        is_first = index == 0
        is_last = index == tick_count - 1

        if is_last and tick_count > 1:
            anchor = "end"
            left_edge = x - label_width
        elif is_first:
            anchor = "start"
            left_edge = x
        else:
            anchor = "middle"
            left_edge = x - label_width / 2

        if left_edge < prev_right_edge + min_gap:
            continue

        prev_right_edge = left_edge + label_width

        x_ticks.append(
            f'<line x1="{x:.1f}" y1="{margin_top}" x2="{x:.1f}" y2="{margin_top + chart_height}" '
            'stroke="#f1f5f9" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{height - 16}" text-anchor="{anchor}" '
            'font-size="12" fill="#475569">'
            f"{escape(label)}</text>"
        )

    legend_y = 16
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Pod and Selenium memory usage">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'{"".join(y_ticks)}'
        f'{"".join(x_ticks)}'
        f'<line x1="{margin_left}" y1="{margin_top + chart_height}" '
        f'x2="{margin_left + chart_width}" y2="{margin_top + chart_height}" '
        'stroke="#94a3b8" stroke-width="1.5"/>'
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + chart_height}" '
        'stroke="#94a3b8" stroke-width="1.5"/>'
        f'{_legend(24, legend_y, "#0f172a", "Pod total")}'
        f'{_legend(164, legend_y, "#2563eb", "Selenium")}'
        f'<path d="{pod_path}" fill="none" stroke="#0f172a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<path d="{selenium_path}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )


def _build_line_path(points: tuple[tuple[float, float], ...] | list[tuple[float, float]] | collections.abc.Iterable[tuple[float, float]]) -> str:
    point_list = list(points)
    if not point_list:
        return ""
    commands = [f"M {point_list[0][0]:.1f} {point_list[0][1]:.1f}"]
    commands.extend(f"L {x:.1f} {y:.1f}" for x, y in point_list[1:])
    return " ".join(commands)


def _legend(x: int, y: int, color: str, label: str) -> str:
    return (
        f'<line x1="{x}" y1="{y}" x2="{x + 18}" y2="{y}" stroke="{color}" stroke-width="3"/>'
        f'<text x="{x + 24}" y="{y + 4}" font-size="12" fill="#334155">{escape(label)}</text>'
    )


def _format_tick(timestamp: datetime) -> str:
    return f"{timestamp.month}月{timestamp.day}日 {timestamp.strftime('%H:%M')}"


def _empty_svg(*, width: int, height: int, message: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(message)}">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<text x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle" '
        'font-size="16" fill="#64748b">'
        f"{escape(message)}</text></svg>"
    )
