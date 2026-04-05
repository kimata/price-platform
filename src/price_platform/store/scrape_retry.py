"""スクレイプ処理向けの共通リトライヘルパー。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import selenium.common.exceptions

logger = logging.getLogger(__name__)

PriceT = TypeVar("PriceT")


class ItemTimingProtocol(Protocol):
    """Minimal metrics timing interface used by scrape retries."""

    def success(self) -> None: ...

    def failure(self, error_message: str | None = None) -> None: ...


@dataclass(frozen=True)
class ScrapeRetryOutcome(Generic[PriceT]):
    """Normalized scrape retry result."""

    prices: list[PriceT]
    success: bool
    error_message: str | None = None


def run_scrape_with_retry(
    *,
    execute: Callable[[], list[PriceT]],
    store_name: str,
    item_name: str,
    max_attempts: int,
    retry_delay_sec: float,
    item_timing: ItemTimingProtocol | None = None,
    on_timeout: Callable[[], object] | None = None,
    on_success: Callable[[], object] | None = None,
) -> ScrapeRetryOutcome[PriceT]:
    """Run a scrape function with shared retry and metrics behavior."""
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            prices = execute()

            if on_success is not None:
                on_success()
            if item_timing is not None:
                item_timing.success()

            return ScrapeRetryOutcome(prices=prices, success=True)

        except selenium.common.exceptions.TimeoutException as exc:
            last_error = exc
            if on_timeout is not None:
                on_timeout()

            if attempt < max_attempts - 1:
                logger.warning(f"{store_name}: {item_name} - タイムアウト、リトライ: {exc}")
                time.sleep(retry_delay_sec)
            else:
                logger.error(f"❌ {store_name}: {item_name} - リトライ失敗（タイムアウト）: {exc}")

        except Exception as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                logger.warning(f"{store_name}: {item_name} - エラー、リトライ: {exc}")
                time.sleep(retry_delay_sec)
            else:
                logger.error(f"❌ {store_name}: {item_name} - リトライ失敗: {exc}")

    error_message = str(last_error)
    if item_timing is not None:
        item_timing.failure(error_message)

    return ScrapeRetryOutcome(
        prices=[],
        success=False,
        error_message=error_message,
    )
