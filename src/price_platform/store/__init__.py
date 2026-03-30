"""Shared store-layer helpers."""

from .fetcher_common import (
    ColorLabelFilterConfig,
    ProductNameFilterConfig,
    ReferencePrices,
    SharedBaseFetcher,
    exclude_suspicious_prices,
    filter_by_color_label,
    filter_by_product_name_match,
)
from .price_event_detector import PriceContext, PriceEventConfig, PriceEventDetector
from .price_event_store import BasePriceEventStore
from .scrape_retry import ScrapeRetryOutcome, run_scrape_with_retry
from .selection import append_selection_filter, build_current_prices_filter, resolve_selection_value
from .webdriver_pool import BaseWebDriverPool

__all__ = [
    "BasePriceEventStore",
    "ColorLabelFilterConfig",
    "PriceContext",
    "PriceEventConfig",
    "PriceEventDetector",
    "ProductNameFilterConfig",
    "ReferencePrices",
    "ScrapeRetryOutcome",
    "SharedBaseFetcher",
    "BaseWebDriverPool",
    "append_selection_filter",
    "build_current_prices_filter",
    "exclude_suspicious_prices",
    "filter_by_color_label",
    "filter_by_product_name_match",
    "resolve_selection_value",
    "run_scrape_with_retry",
]
