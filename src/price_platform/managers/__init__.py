"""Manager modules for price-platform applications.

Provides shared lifecycle, liveness, and metrics management
for crawl-based price tracking applications.
"""

from .crawl_runtime import CrawlRuntime, managed_crawl_runtime
from .lifecycle_manager import (
    LifecycleManager,
    get_exit_reason,
    get_lifecycle_manager,
    init_lifecycle_manager,
    is_shutdown_requested,
    request_shutdown,
    reset_shutdown,
    set_lifecycle_manager,
)
from .liveness_manager import (
    LivenessManager,
    get_liveness_manager,
    init_liveness_manager,
    set_liveness_manager,
)
from .metrics_manager import (
    MetricsDBProtocol,
    MetricsManager,
    get_metrics_manager,
    set_metrics_manager,
)

__all__ = [
    "LifecycleManager",
    "LivenessManager",
    "MetricsDBProtocol",
    "MetricsManager",
    "CrawlRuntime",
    "get_exit_reason",
    "get_lifecycle_manager",
    "get_liveness_manager",
    "get_metrics_manager",
    "init_lifecycle_manager",
    "init_liveness_manager",
    "is_shutdown_requested",
    "managed_crawl_runtime",
    "request_shutdown",
    "reset_shutdown",
    "set_lifecycle_manager",
    "set_liveness_manager",
    "set_metrics_manager",
]
