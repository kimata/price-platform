"""ブラウザ関連ヘルパーの薄い集約層。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from my_lib.browser_manager import BrowserManager
else:
    BrowserManager = object


def create_browser_manager(
    *,
    profile_name: str,
    data_dir: Path,
    clear_profile_on_error: bool = True,
    max_retry_on_error: int = 2,
) -> BrowserManager:
    from my_lib.browser_manager import BrowserManager as BrowserManagerImpl

    return BrowserManagerImpl(
        profile_name=profile_name,
        data_dir=data_dir,
        clear_profile_on_error=clear_profile_on_error,
        max_retry_on_error=max_retry_on_error,
    )


def create_driver(*, profile_name: str, data_path: Path, is_headless: bool) -> WebDriver:
    from my_lib.selenium_util import create_driver as create_driver_impl

    return create_driver_impl(
        profile_name=profile_name,
        data_path=data_path,
        is_headless=is_headless,
    )


def quit_driver_gracefully(driver: WebDriver) -> None:
    from my_lib.selenium_util import quit_driver_gracefully as quit_driver_gracefully_impl

    quit_driver_gracefully_impl(driver)


def clear_cache(driver: WebDriver) -> None:
    from my_lib.selenium_util import clear_cache as clear_cache_impl

    clear_cache_impl(driver)
