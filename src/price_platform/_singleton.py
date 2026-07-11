"""グローバルシングルトンの共通ホルダー。

metrics_sqlite / client_metrics_sqlite でコピペ重複していた
get / init / _reset の三点セットを一箇所に集約する (R10)。
"""

from __future__ import annotations


class SingletonHolder[T]:
    """初期化必須のグローバルインスタンスを保持する小さなホルダー。"""

    def __init__(self, name: str, init_hint: str):
        self._name = name
        self._init_hint = init_hint
        self._instance: T | None = None

    def get(self) -> T:
        if self._instance is None:
            raise RuntimeError(f"{self._name} not initialized. Call {self._init_hint} first.")
        return self._instance

    def set(self, instance: T) -> T:
        self._instance = instance
        return instance

    def reset(self) -> None:
        self._instance = None
