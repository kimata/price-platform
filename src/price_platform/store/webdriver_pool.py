"""Shared WebDriver pool primitives for scrape engines."""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

import my_lib.browser_manager
import my_lib.selenium_util

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support.wait import WebDriverWait

logger = logging.getLogger(__name__)

MakerT = TypeVar("MakerT")
ConfigT = TypeVar("ConfigT")


@dataclass
class BaseWebDriverPool(Generic[MakerT, ConfigT]):
    """WebDriver pool keyed by maker-like objects with a ``value`` field."""

    MAX_CONSECUTIVE_TIMEOUTS: ClassVar[int] = 10

    config: ConfigT
    profile_name_getter: Callable[[MakerT], str]
    page_load_timeout: int | None = None
    _managers: dict[MakerT, my_lib.browser_manager.BrowserManager] = field(default_factory=dict, init=False)
    _consecutive_timeout_counts: dict[MakerT, int] = field(default_factory=dict, init=False)

    def _get_or_create_manager(self, maker: MakerT) -> my_lib.browser_manager.BrowserManager:
        if maker not in self._managers:
            data_path = pathlib.Path(self.config.selenium.data_path)
            profile_name = self.profile_name_getter(maker)
            self._managers[maker] = my_lib.browser_manager.BrowserManager(
                profile_name=profile_name,
                data_dir=data_path,
                clear_profile_on_error=True,
                max_retry_on_error=2,
            )
            logger.info("WebDriver を作成: %s", profile_name)
        return self._managers[maker]

    def get(self, maker: MakerT) -> tuple[WebDriver, WebDriverWait]:
        manager = self._get_or_create_manager(maker)
        driver, wait = manager.get_driver()
        if self.page_load_timeout is not None:
            driver.set_page_load_timeout(self.page_load_timeout)
        return driver, wait

    def notify_timeout(self, maker: MakerT) -> bool:
        count = self._consecutive_timeout_counts.get(maker, 0) + 1
        self._consecutive_timeout_counts[maker] = count
        maker_name = getattr(maker, "value", str(maker))
        logger.warning("%s: 連続タイムアウト: %d/%d", maker_name, count, self.MAX_CONSECUTIVE_TIMEOUTS)

        if count >= self.MAX_CONSECUTIVE_TIMEOUTS:
            self._restart_with_clean_profile(maker)
            return True
        return False

    def notify_success(self, maker: MakerT) -> None:
        count = self._consecutive_timeout_counts.get(maker, 0)
        maker_name = getattr(maker, "value", str(maker))
        if count > 0:
            logger.debug("%s: 連続タイムアウトカウントをリセット（%d → 0）", maker_name, count)
        self._consecutive_timeout_counts[maker] = 0

    def _restart_with_clean_profile(self, maker: MakerT) -> None:
        manager = self._managers.get(maker)
        if manager is None:
            return

        maker_name = getattr(maker, "value", str(maker))
        count = self._consecutive_timeout_counts.get(maker, 0)
        logger.warning("%s: 連続 %d 件のタイムアウトが発生したため、ドライバーを再起動します", maker_name, count)
        manager.restart_with_clean_profile()
        self._consecutive_timeout_counts[maker] = 0
        logger.info("%s: ドライバーの再起動が完了しました", maker_name)

    def close_all(self) -> None:
        for maker, manager in self._managers.items():
            logger.debug("WebDriver を終了: %s", self.profile_name_getter(maker))
            manager.quit()
        self._managers.clear()
        self._consecutive_timeout_counts.clear()

    def clear_cache(self) -> None:
        for maker, manager in self._managers.items():
            driver, _ = manager.get_driver()
            my_lib.selenium_util.clear_cache(driver)
            logger.info("ブラウザキャッシュをクリア: %s", self.profile_name_getter(maker))

    def __enter__(self) -> BaseWebDriverPool[MakerT, ConfigT]:
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        self.close_all()
