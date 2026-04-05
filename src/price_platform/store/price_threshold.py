"""Shared helpers for loading price-threshold data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, TypeVar

from my_lib.platform import config as platform_config

ThresholdT = TypeVar("ThresholdT", bound="SupportsPriceThreshold")


class SupportsPriceThreshold(Protocol):
    name: str
    price_min: int


def load_price_threshold_map(
    *,
    threshold_path: Path,
    schema_path: Path,
    parser: type[ThresholdT] | object,
    logger: logging.Logger,
) -> dict[str, int]:
    """Load ``name -> price_min`` mappings from the shared YAML format."""
    if not threshold_path.exists():
        logger.info("price_threshold.yaml not found, using empty threshold")
        return {}

    parse = getattr(parser, "parse")
    try:
        data = platform_config.load(threshold_path, schema_path, include_base_dir=False)
        if data is None or not isinstance(data, list):
            return {}
        thresholds = [parse(item) for item in data if isinstance(item, dict)]
        return {threshold.name: threshold.price_min for threshold in thresholds}
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load price_threshold.yaml: %s", exc)
        return {}
