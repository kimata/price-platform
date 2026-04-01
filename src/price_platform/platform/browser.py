"""Adapters for browser-related helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    import my_lib.platform.browser

    BrowserManager = my_lib.platform.browser.BrowserManager
else:
    BrowserManager = object


def create_browser_manager(
    *,
    profile_name: str,
    data_dir: Path,
    clear_profile_on_error: bool = True,
    max_retry_on_error: int = 2,
) -> BrowserManager:
    import my_lib.platform.browser

    return my_lib.platform.browser.BrowserManager(
        profile_name=profile_name,
        data_dir=data_dir,
        clear_profile_on_error=clear_profile_on_error,
        max_retry_on_error=max_retry_on_error,
    )


def create_driver(*, profile_name: str, data_path: Path, is_headless: bool) -> WebDriver:
    import my_lib.platform.browser

    return my_lib.platform.browser.create_driver(
        profile_name=profile_name,
        data_path=data_path,
        is_headless=is_headless,
    )


def quit_driver_gracefully(driver: WebDriver) -> None:
    import my_lib.platform.browser

    my_lib.platform.browser.quit_driver_gracefully(driver)


def clear_cache(driver: WebDriver) -> None:
    import my_lib.platform.browser

    my_lib.platform.browser.clear_cache(driver)
