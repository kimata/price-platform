from __future__ import annotations

from dataclasses import dataclass

import pytest
import selenium.common.exceptions

from price_platform.store.scrape_retry import run_scrape_with_retry


@dataclass
class DummyItemTiming:
    success_count: int = 0
    failure_messages: list[str | None] | None = None

    def __post_init__(self) -> None:
        if self.failure_messages is None:
            self.failure_messages = []

    def success(self) -> None:
        self.success_count += 1

    def failure(self, error_message: str | None = None) -> None:
        assert self.failure_messages is not None
        self.failure_messages.append(error_message)


def test_run_scrape_with_retry_retries_timeout_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    timeouts = 0
    successes = 0
    item_timing = DummyItemTiming()

    def execute() -> list[int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise selenium.common.exceptions.TimeoutException("slow")
        return [1, 2]

    def on_timeout() -> None:
        nonlocal timeouts
        timeouts += 1

    def on_success() -> None:
        nonlocal successes
        successes += 1

    monkeypatch.setattr("price_platform.store.scrape_retry.time.sleep", lambda _: None)

    outcome = run_scrape_with_retry(
        execute=execute,
        store_name="mercari",
        item_name="sample",
        max_attempts=2,
        retry_delay_sec=0.1,
        item_timing=item_timing,
        on_timeout=on_timeout,
        on_success=on_success,
    )

    assert outcome.success is True
    assert outcome.prices == [1, 2]
    assert timeouts == 1
    assert successes == 1
    assert item_timing.success_count == 1
    assert item_timing.failure_messages == []


def test_run_scrape_with_retry_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts = 0
    item_timing = DummyItemTiming()

    def execute() -> list[int]:
        raise selenium.common.exceptions.TimeoutException("slow")

    def on_timeout() -> None:
        nonlocal timeouts
        timeouts += 1

    monkeypatch.setattr("price_platform.store.scrape_retry.time.sleep", lambda _: None)

    outcome = run_scrape_with_retry(
        execute=execute,
        store_name="mercari",
        item_name="sample",
        max_attempts=2,
        retry_delay_sec=0.1,
        item_timing=item_timing,
        on_timeout=on_timeout,
    )

    assert outcome.success is False
    assert outcome.prices == []
    assert outcome.error_message == "Message: slow\n"
    assert timeouts == 2
    assert item_timing.success_count == 0
    assert item_timing.failure_messages == ["Message: slow\n"]
