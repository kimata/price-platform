"""クロール/クライアントメトリクスの収集・集計・描画 (R6 で再編)。

- server: クローラー側のセッション/アイテム統計 (MetricsDB)
- client: ブラウザ側のパフォーマンス/Web Vitals 統計 (ClientMetricsDB)
- render: SVG 描画 (箱ひげ図・メモリ推移)
"""

from .client.db import (
    ClientMetricsDB,
    get_client_metrics_db,
    init_client_metrics_db,
    open_client_metrics_db,
)
from .server.db import (
    MetricsDB,
    get_metrics_db,
    init_metrics_db,
    open_metrics_db,
)

__all__ = [
    "ClientMetricsDB",
    "MetricsDB",
    "get_client_metrics_db",
    "get_metrics_db",
    "init_client_metrics_db",
    "init_metrics_db",
    "open_client_metrics_db",
    "open_metrics_db",
]
