"""ストア層の共通ヘルパーと遅延 re-export。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._price_event_enum import PriceEventType as PriceEventType
    from ._price_event_message import (
        format_event_message as format_event_message,
    )
    from ._price_event_message import (
        format_event_message_from_event as format_event_message_from_event,
    )
    from .fetcher_common import (
        ColorLabelFilterConfig as ColorLabelFilterConfig,
    )
    from .fetcher_common import (
        FilterDecision as FilterDecision,
    )
    from .fetcher_common import (
        FilterReason as FilterReason,
    )
    from .fetcher_common import (
        FilterResult as FilterResult,
    )
    from .fetcher_common import (
        ProductNameRule as ProductNameRule,
    )
    from .fetcher_common import (
        ReferencePrices as ReferencePrices,
    )
    from .fetcher_common import (
        SharedBaseFetcher as SharedBaseFetcher,
    )
    from .fetcher_common import (
        default_keyword_in_title as default_keyword_in_title,
    )
    from .fetcher_common import (
        exclude_suspicious_prices as exclude_suspicious_prices,
    )
    from .fetcher_common import (
        filter_by_color_label as filter_by_color_label,
    )
    from .fetcher_common import (
        filter_by_product_name_match as filter_by_product_name_match,
    )
    from .price_event_detector import (
        PriceContext as PriceContext,
    )
    from .price_event_detector import (
        PriceEventConfig as PriceEventConfig,
    )
    from .price_event_detector import (
        PriceEventDetector as PriceEventDetector,
    )
    from .price_event_store import BasePriceEventStore as BasePriceEventStore
    from .scrape_retry import (
        ScrapeRetryOutcome as ScrapeRetryOutcome,
    )
    from .scrape_retry import (
        run_scrape_with_retry as run_scrape_with_retry,
    )
    from .selection import (
        append_selection_filter as append_selection_filter,
    )
    from .selection import (
        build_current_prices_filter as build_current_prices_filter,
    )
    from .shuffle import group_shuffle as group_shuffle
    from .webdriver_pool import BaseWebDriverPool as BaseWebDriverPool

_EXPORTS = {
    "ColorLabelFilterConfig": (".fetcher_common", "ColorLabelFilterConfig"),
    "default_keyword_in_title": (".fetcher_common", "default_keyword_in_title"),
    "FilterDecision": (".fetcher_common", "FilterDecision"),
    "FilterReason": (".fetcher_common", "FilterReason"),
    "FilterResult": (".fetcher_common", "FilterResult"),
    "ProductNameRule": (".fetcher_common", "ProductNameRule"),
    "ReferencePrices": (".fetcher_common", "ReferencePrices"),
    "SharedBaseFetcher": (".fetcher_common", "SharedBaseFetcher"),
    "exclude_suspicious_prices": (".fetcher_common", "exclude_suspicious_prices"),
    "filter_by_color_label": (".fetcher_common", "filter_by_color_label"),
    "filter_by_product_name_match": (".fetcher_common", "filter_by_product_name_match"),
    "PriceContext": (".price_event_detector", "PriceContext"),
    "PriceEventConfig": (".price_event_detector", "PriceEventConfig"),
    "PriceEventDetector": (".price_event_detector", "PriceEventDetector"),
    "PriceEventType": ("._price_event_enum", "PriceEventType"),
    "format_event_message": ("._price_event_message", "format_event_message"),
    "format_event_message_from_event": ("._price_event_message", "format_event_message_from_event"),
    "BasePriceEventStore": (".price_event_store", "BasePriceEventStore"),
    "ScrapeRetryOutcome": (".scrape_retry", "ScrapeRetryOutcome"),
    "run_scrape_with_retry": (".scrape_retry", "run_scrape_with_retry"),
    "append_selection_filter": (".selection", "append_selection_filter"),
    "build_current_prices_filter": (".selection", "build_current_prices_filter"),
    "group_shuffle": (".shuffle", "group_shuffle"),
    "BaseWebDriverPool": (".webdriver_pool", "BaseWebDriverPool"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from exc

    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals()) + __all__)
