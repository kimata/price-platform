"""Manager modules for price-platform applications.

Provides shared lifecycle, liveness, and metrics management
for crawl-based price tracking applications.
"""

from .crawl_runtime import CrawlRuntime, managed_crawl_runtime
from .lifecycle_manager import LifecycleManager
from .liveness_manager import LivenessManager
from .metrics_manager import MetricsDBProtocol, MetricsManager, SessionMemoryTrackerProtocol
from .pod_memory_tracker import MemorySample, MemorySeriesSnapshot, PodMemoryTracker

__all__ = [
    "LifecycleManager",
    "LivenessManager",
    "MetricsDBProtocol",
    "MetricsManager",
    "SessionMemoryTrackerProtocol",
    "MemorySample",
    "MemorySeriesSnapshot",
    "PodMemoryTracker",
    "CrawlRuntime",
    "managed_crawl_runtime",
]
