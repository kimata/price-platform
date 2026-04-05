"""price-platform Web アプリ向けの CORS ヘルパー。"""

from __future__ import annotations

import ipaddress
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


def _is_local_origin(origin: str) -> bool:
    """Return True if *origin* points to localhost or a private IP."""
    parsed = urllib.parse.urlparse(origin)
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def is_allowed_request_origin(
    *,
    allowed_origins: list[str] | tuple[str, ...],
    origin: str | None,
    referer: str | None,
) -> bool:
    """Return whether a request origin or referer matches the allowed origin list.

    Requests from localhost or private-IP origins are always accepted
    when an Origin header is present (CI / E2E environments).
    """
    if origin and origin in allowed_origins:
        return True

    if origin and _is_local_origin(origin):
        return True

    referer_origin = extract_origin(referer)
    return referer_origin in allowed_origins if referer_origin else False
