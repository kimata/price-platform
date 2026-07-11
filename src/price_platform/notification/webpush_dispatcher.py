"""Web Push 送信の非同期ディスパッチャ (F2)。

Twitter 側 (キュー + ワーカースレッド) と非対称だった Web Push の同期直列送信を
バックグラウンドワーカーに移し、イベント検出スレッド (クローラ) を
購読者数 × レイテンシ分ブロックしないようにする (B11 の恒久対応)。

送信履歴は webpush_delivery_logs に、購読単位の失敗リトライ打ち切りは
連続失敗カウント (B12) に、それぞれ既存機構で記録される。
1 件も成功しなかった送信 (Push サービス側の一時障害など) に限り、
重複送信の危険なしにジョブ全体を再試行する。
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

# ワーカー停止時にキューの残りを待つ最大秒数
_STOP_JOIN_TIMEOUT_SEC = 30.0


class _SenderProtocol(Protocol):
    def send_to_all(self, event: Any, product: Any) -> Any: ...


EventT = TypeVar("EventT")
ProductT = TypeVar("ProductT")


@dataclass(frozen=True)
class _SendJob[EventT, ProductT]:
    event: EventT
    product: ProductT
    attempt: int = 0


class WebPushDispatcher[EventT, ProductT]:
    """Web Push 送信ジョブをワーカースレッドで直列処理する。"""

    def __init__(
        self,
        sender: _SenderProtocol,
        *,
        max_retries: int = 2,
        retry_delay_sec: float = 60.0,
    ):
        self._sender = sender
        self._max_retries = max_retries
        self._retry_delay_sec = retry_delay_sec
        self._queue: queue.Queue[_SendJob[EventT, ProductT] | None] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            logger.warning("WebPush dispatcher is already running")
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker, name="webpush-dispatcher", daemon=True
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)  # ワーカーを起こす
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=_STOP_JOIN_TIMEOUT_SEC)
            if self._worker_thread.is_alive():
                logger.warning("WebPush dispatcher did not stop within timeout")
            self._worker_thread = None

    @property
    def is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    def submit(self, event: EventT, product: ProductT) -> None:
        """送信ジョブを登録する (非ブロッキング)。"""
        self._queue.put(_SendJob(event=event, product=product))

    def _worker(self) -> None:
        logger.debug("WebPush dispatcher worker started")
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                continue
            try:
                self._process(job)
            except Exception:
                logger.exception("Error in WebPush dispatcher worker")
        logger.debug("WebPush dispatcher worker stopped")

    def _process(self, job: _SendJob[EventT, ProductT]) -> None:
        result = self._sender.send_to_all(job.event, job.product)

        success = getattr(result, "success_count", 0)
        failed = getattr(result, "failed_count", 0)
        expired = getattr(result, "expired_count", 0)
        if success > 0 or failed > 0 or expired > 0:
            logger.info(
                "Web Push 送信: 成功=%d, 失敗=%d, 期限切れ=%d",
                success,
                failed,
                expired,
            )

        # 1 件も成功していない失敗 (Push サービス側の一時障害など) のみ全体を再試行する。
        # 部分成功のジョブを再試行すると成功済み購読への重複送信になるため行わない。
        if success == 0 and failed > 0 and job.attempt < self._max_retries:
            if self._stop_event.wait(self._retry_delay_sec):
                return
            logger.info("Web Push 送信を再試行します (attempt=%d)", job.attempt + 1)
            self._queue.put(_SendJob(event=job.event, product=job.product, attempt=job.attempt + 1))
