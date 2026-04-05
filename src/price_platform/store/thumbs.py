"""Shared helpers for item thumbnail naming."""

from __future__ import annotations

import hashlib
from typing import Protocol


class SupportsStoreValue(Protocol):
    @property
    def value(self) -> str: ...


def generate_thumb_filename(url: str, store: SupportsStoreValue | str) -> str:
    """Generate a deterministic thumbnail filename."""
    store_value = store if isinstance(store, str) else store.value
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"{store_value}_{url_hash}.jpg"
