"""クライアントメトリクス集計で共有する四分位統計。"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QuartileStats:
    """値集合の min / q1 / median / q3 / max / avg。"""

    min_val: float
    q1: float
    median: float
    q3: float
    max_val: float
    avg: float
    count: int


def compute_quartiles(values: Sequence[float]) -> QuartileStats | None:
    """四分位統計を計算する。values が空の場合は None。"""
    if not values:
        return None

    sorted_values = sorted(values)
    n = len(sorted_values)
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    return QuartileStats(
        min_val=sorted_values[0],
        q1=sorted_values[q1_idx] if q1_idx < n else sorted_values[0],
        median=statistics.median(sorted_values),
        q3=sorted_values[q3_idx] if q3_idx < n else sorted_values[-1],
        max_val=sorted_values[-1],
        avg=statistics.mean(sorted_values),
        count=n,
    )
