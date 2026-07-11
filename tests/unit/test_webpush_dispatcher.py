"""WebPushDispatcher のテスト (F2)。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from price_platform.notification.webpush_dispatcher import WebPushDispatcher
from price_platform.notification.webpush_sender import WebPushResult


@dataclass
class _FakeSender:
    results: list[WebPushResult] = field(default_factory=list)
    calls: list[tuple[object, object]] = field(default_factory=list)
    event: threading.Event = field(default_factory=threading.Event)

    def send_to_all(self, event: object, product: object) -> WebPushResult:
        self.calls.append((event, product))
        self.event.set()
        if self.results:
            return self.results.pop(0)
        return WebPushResult(success_count=1, failed_count=0, expired_count=0)


def _wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_submit_is_non_blocking_and_sends_in_background() -> None:
    sender = _FakeSender()
    dispatcher = WebPushDispatcher(sender)
    dispatcher.start()
    try:
        dispatcher.submit("event-1", "product-1")
        assert _wait_for(lambda: len(sender.calls) == 1)
        assert sender.calls[0] == ("event-1", "product-1")
    finally:
        dispatcher.stop()
    assert not dispatcher.is_running


def test_total_failure_is_retried() -> None:
    sender = _FakeSender(
        results=[
            WebPushResult(success_count=0, failed_count=2, expired_count=0),
            WebPushResult(success_count=2, failed_count=0, expired_count=0),
        ]
    )
    dispatcher = WebPushDispatcher(sender, max_retries=2, retry_delay_sec=0.01)
    dispatcher.start()
    try:
        dispatcher.submit("event-1", "product-1")
        assert _wait_for(lambda: len(sender.calls) == 2), "全滅した送信が再試行されない"
    finally:
        dispatcher.stop()


def test_partial_success_is_not_retried() -> None:
    sender = _FakeSender(
        results=[WebPushResult(success_count=1, failed_count=1, expired_count=0)]
    )
    dispatcher = WebPushDispatcher(sender, max_retries=2, retry_delay_sec=0.01)
    dispatcher.start()
    try:
        dispatcher.submit("event-1", "product-1")
        assert _wait_for(lambda: len(sender.calls) == 1)
        time.sleep(0.1)
        assert len(sender.calls) == 1, "部分成功のジョブが再試行された (重複送信の危険)"
    finally:
        dispatcher.stop()


def test_stop_terminates_worker() -> None:
    dispatcher = WebPushDispatcher(_FakeSender())
    dispatcher.start()
    assert dispatcher.is_running
    dispatcher.stop()
    assert not dispatcher.is_running
