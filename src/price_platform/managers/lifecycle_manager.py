"""price-platform アプリ向けのライフサイクル管理。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LifecycleManager:
    """シャットダウン連携を扱うスレッドセーフな管理クラス。"""

    _shutdown_event: threading.Event = field(default_factory=threading.Event)
    _exit_reason: str | None = field(default=None)

    def request_shutdown(self, exit_reason: str = "shutdown") -> None:
        """アプリケーションのシャットダウンを要求する。"""
        self._exit_reason = exit_reason
        self._shutdown_event.set()
        logger.info(f"シャットダウンが要求されました (reason: {exit_reason})")

    def is_shutdown_requested(self) -> bool:
        """シャットダウン要求済みかを返す。"""
        return self._shutdown_event.is_set()

    def get_exit_reason(self) -> str | None:
        """シャットダウン理由を返す。未要求なら `None` を返す。"""
        return self._exit_reason

    def reset(self) -> None:
        """シャットダウン状態を初期化する。"""
        self._shutdown_event.clear()
        self._exit_reason = None
        logger.debug("シャットダウン状態をリセット")

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """シャットダウン要求が入るまで待機する。"""
        return self._shutdown_event.wait(timeout)
