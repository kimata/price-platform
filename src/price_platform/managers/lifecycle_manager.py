"""price-platform アプリ向けのライフサイクル管理。"""

from __future__ import annotations

from my_lib.lifecycle.shutdown import ShutdownController


class LifecycleManager(ShutdownController):
    """シャットダウン連携を扱うスレッドセーフな管理クラス。"""
