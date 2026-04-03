"""Product shuffle utilities for scrape engines."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
K = TypeVar("K")


def group_shuffle(items: list[T], *, key: Callable[[T], K]) -> list[T]:
    """グループ内シャッフル + グループ間シャッフルを行う。

    *key* で同じ値を返すアイテムを1つのグループとし、
    グループ内の順序とグループ自体の順序を両方シャッフルする。
    これにより、同一グループのアイテムが連続して処理される。

    >>> # カテゴリごとにまとめつつランダム化
    >>> group_shuffle(products, key=lambda p: p.category)
    """
    groups: dict[K, list[T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)

    group_list = list(groups.values())
    random.shuffle(group_list)
    for group in group_list:
        random.shuffle(group)

    return [item for group in group_list for item in group]
