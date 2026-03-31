"""SVG rendering helpers for client metrics charts."""

from __future__ import annotations

import functools

from ._client_metrics_sqlite_models import BoxplotData


@functools.cache
def generate_boxplot_svg(
    data: tuple[BoxplotData, ...],
    title: str,
    width: int = 800,
    height: int = 400,
) -> str:
    if not data:
        return _generate_empty_svg(title, width, height)

    dates = sorted({d.date for d in data})
    if len(dates) > 30:
        dates = dates[-30:]

    margin_left = 60
    margin_right = 20
    margin_top = 50
    margin_bottom = 60
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom

    all_values = [d.max_val for d in data] + [d.min_val for d in data]
    y_min = 0
    y_max = min(max(all_values) * 1.1, 2000) if all_values else 1000

    def y_scale(val: float) -> float:
        return margin_top + chart_height - (val - y_min) / (y_max - y_min) * chart_height

    box_width = min(20, chart_width / len(dates) / 3)
    group_width = chart_width / len(dates)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        "<style>",
        ".box-mobile { fill: #4ade80; stroke: #16a34a; stroke-width: 1; }",
        ".box-desktop { fill: #60a5fa; stroke: #2563eb; stroke-width: 1; }",
        ".whisker { stroke: #374151; stroke-width: 1; }",
        ".median { stroke: #111827; stroke-width: 2; }",
        ".axis { stroke: #9ca3af; stroke-width: 1; }",
        ".label { font-family: sans-serif; font-size: 10px; fill: #374151; }",
        ".title { font-family: sans-serif; font-size: 14px; fill: #111827; font-weight: bold; }",
        ".legend { font-family: sans-serif; font-size: 11px; fill: #374151; }",
        "</style>",
        f'<text x="{width / 2}" y="25" class="title" text-anchor="middle">{title}</text>',
        f'<rect x="{width - 150}" y="10" width="12" height="12" class="box-mobile" />',
        f'<text x="{width - 135}" y="20" class="legend">Mobile</text>',
        f'<rect x="{width - 80}" y="10" width="12" height="12" class="box-desktop" />',
        f'<text x="{width - 65}" y="20" class="legend">Desktop</text>',
    ]

    y_axis_y2 = margin_top + chart_height
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{y_axis_y2}" class="axis" />'
    )
    x_axis_x2 = margin_left + chart_width
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{y_axis_y2}" x2="{x_axis_x2}" y2="{y_axis_y2}" class="axis" />'
    )

    step = 500 if y_max > 2000 else 200 if y_max > 1000 else 100
    y_val = 0
    while y_val <= y_max:
        y_pos = y_scale(y_val)
        svg_parts.append(
            f'<text x="{margin_left - 5}" y="{y_pos + 4}" class="label" text-anchor="end">{int(y_val)}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y_pos}" x2="{x_axis_x2}" y2="{y_pos}" stroke="#e5e7eb" stroke-width="1" />'
        )
        y_val += step

    for i, date_str in enumerate(dates):
        x_center = margin_left + (i + 0.5) * group_width
        date_data = [d for d in data if d.date == date_str]
        day = int(date_str.split("-")[2])
        label = f"{int(date_str.split('-')[1])}/{day}" if day == 1 or i == 0 else str(day)
        label_y = y_axis_y2 + 15
        svg_parts.append(f'<text x="{x_center}" y="{label_y}" class="label" text-anchor="middle">{label}</text>')

        for d in date_data:
            x_offset = -box_width * 0.6 if d.device_type == "mobile" else box_width * 0.6
            x = x_center + x_offset
            box_class = "box-mobile" if d.device_type == "mobile" else "box-desktop"
            y_min_pt = y_scale(d.min_val)
            y_max_pt = y_scale(d.max_val)
            y_median = y_scale(d.median)
            cap_x1 = x - box_width / 4
            cap_x2 = x + box_width / 4
            box_x = x - box_width / 2

            svg_parts.append(f'<line x1="{x}" y1="{y_min_pt}" x2="{x}" y2="{y_max_pt}" class="whisker" />')
            svg_parts.append(f'<line x1="{cap_x1}" y1="{y_min_pt}" x2="{cap_x2}" y2="{y_min_pt}" class="whisker" />')
            svg_parts.append(f'<line x1="{cap_x1}" y1="{y_max_pt}" x2="{cap_x2}" y2="{y_max_pt}" class="whisker" />')
            box_top = y_scale(d.q3)
            box_bottom = y_scale(d.q1)
            box_height = box_bottom - box_top
            svg_parts.append(
                f'<rect x="{box_x}" y="{box_top}" width="{box_width}" height="{box_height}" class="{box_class}" />'
            )
            svg_parts.append(
                f'<line x1="{box_x}" y1="{y_median}" x2="{x + box_width / 2}" y2="{y_median}" class="median" />'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _generate_empty_svg(title: str, width: int, height: int) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
    <style>
        .title {{ font-family: sans-serif; font-size: 14px; fill: #111827; font-weight: bold; }}
        .message {{ font-family: sans-serif; font-size: 12px; fill: #6b7280; }}
    </style>
    <text x="{width / 2}" y="25" class="title" text-anchor="middle">{title}</text>
    <text x="{width / 2}" y="{height / 2}" class="message" text-anchor="middle">データがありません</text>
</svg>"""
