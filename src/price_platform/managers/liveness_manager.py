"""price-platform アプリ向けの liveness 管理。"""

from __future__ import annotations

import logging
import pathlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from price_platform.platform import footprint

logger = logging.getLogger(__name__)

# liveness ファイルの既定更新間隔（秒）
DEFAULT_UPDATE_INTERVAL = 30
_liveness_manager: LivenessManager | None = None


def _default_update_fn(path: pathlib.Path) -> None:
    """標準の liveness 更新処理。"""
    footprint.update(path)


@dataclass
class LivenessManager:
    """liveness ファイル更新と中断可能スリープを扱う管理クラス。"""

    liveness_file: pathlib.Path | None
    update_interval_sec: int = DEFAULT_UPDATE_INTERVAL
    update_fn: Callable[[pathlib.Path], None] = field(default=_default_update_fn)

    def update(self) -> None:
        """liveness ファイルを更新する。未設定なら何もしない。"""
        if self.liveness_file is None:
            return

        self.update_fn(self.liveness_file)
        logger.debug(f"liveness を更新しました: {self.liveness_file}")

    def interruptible_sleep(
        self,
        duration_sec: float,
        shutdown_check: Callable[[], bool],
    ) -> bool:
        """シャットダウン検知付きでスリープする。"""
        elapsed = 0.0
        check_interval = float(self.update_interval_sec)

        while elapsed < duration_sec:
            if shutdown_check():
                logger.info("シャットダウンが要求されたため、スリープを中断します")
                return False

            # liveness を更新する
            self.update()

            # 次の待機時間を計算する
            sleep_time = min(check_interval, duration_sec - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

        # 最後にもう一度 liveness を更新する
        self.update()

        return True


def get_liveness_manager() -> LivenessManager | None:
    """プロセス全体で共有する liveness manager を返す。"""
    return _liveness_manager


def set_liveness_manager(manager: LivenessManager | None) -> None:
    """プロセス全体で共有する liveness manager を差し替える。"""
    global _liveness_manager
    _liveness_manager = manager


def init_liveness_manager(
    *,
    liveness_file: pathlib.Path | None,
    update_interval_sec: int = DEFAULT_UPDATE_INTERVAL,
    update_fn: Callable[[pathlib.Path], None] = _default_update_fn,
) -> LivenessManager:
    """プロセス全体で共有する liveness manager を生成して登録する。"""
    manager = LivenessManager(
        liveness_file=liveness_file,
        update_interval_sec=update_interval_sec,
        update_fn=update_fn,
    )
    set_liveness_manager(manager)
    return manager


def _reset_liveness_manager() -> None:
    """テスト用に共有 liveness manager をクリアする。"""
    set_liveness_manager(None)
