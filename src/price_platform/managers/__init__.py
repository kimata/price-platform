"""Manager modules for price-platform applications.

Provides shared lifecycle, liveness, and metrics management
for crawl-based price tracking applications.
"""

from .crawl_runtime import CrawlRuntime, managed_crawl_runtime
from .lifecycle_manager import LifecycleManager
from .liveness_manager import (
    LivenessManager,
    get_liveness_manager,
    init_liveness_manager,
    set_liveness_manager,
)
from .metrics_manager import MetricsDBProtocol, MetricsManager

__all__ = [
    "LifecycleManager",
    "LivenessManager",
    "MetricsDBProtocol",
    "MetricsManager",
    "CrawlRuntime",
    "get_liveness_manager",
    "init_liveness_manager",
    "managed_crawl_runtime",
    "set_liveness_manager",
]
