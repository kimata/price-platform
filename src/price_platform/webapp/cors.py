"""CORS helpers for price-platform web applications."""

from __future__ import annotations

import urllib.parse


def extract_origin(url: str | None) -> str | None:
    """Extract scheme://host[:port] from a URL string."""
    if not url:
        return None

    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}"


def get_cors_origins(external_url: str) -> list[str]:
    """Build a Flask-CORS origins list from an external URL."""
    origin = extract_origin(external_url)
    if origin is None:
        msg = f"Invalid external_url format: {external_url}"
        raise ValueError(msg)
    return [origin]


def is_allowed_request_origin(
    *,
    allowed_origins: list[str] | tuple[str, ...],
    origin: str | None,
    referer: str | None,
) -> bool:
    """Return whether a request origin or referer matches the allowed origin list."""
    if origin and origin in allowed_origins:
        return True

    referer_origin = extract_origin(referer)
    return referer_origin in allowed_origins if referer_origin else False
