"""ブラウザ関連ヘルパーの薄い集約層。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import my_lib.browser

if TYPE_CHECKING:
    from pathlib import Path

# BrowserManager を本モジュール名前空間へ再エクスポート（呼び出し側の型注釈用）。
BrowserManager = my_lib.browser.BrowserManager


def create_browser_manager(
    *,
    profile_name: str,
    data_dir: Path,
    headless: bool = False,
) -> my_lib.browser.BrowserManager:
    """Page 抽象を提供する BrowserManager を生成する。"""
    return my_lib.browser.BrowserManager(
        my_lib.browser.BrowserProfile(
            name=profile_name,
            data_dir=data_dir,
            headless=headless,
        ),
    )
