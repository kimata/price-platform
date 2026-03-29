"""HTTP header helpers for price-platform web applications."""

from __future__ import annotations

from dataclasses import dataclass

import flask


@dataclass(frozen=True)
class CacheRule:
    """Path-prefix based cache rule."""

    path_prefix: str
    max_age: int


def _resolve_cache_control(
    *,
    path: str,
    api_prefix: str,
    cache_rules: list[CacheRule] | tuple[CacheRule, ...],
    token_path_prefix: str = "token",
    default_max_age: int = 600,
) -> str | None:
    if not path.startswith(api_prefix):
        return None

    if path.startswith(f"{api_prefix}{token_path_prefix}"):
        return "no-store"

    for rule in cache_rules:
        if path.startswith(rule.path_prefix):
            return f"public, max-age={rule.max_age}"

    return f"public, max-age={default_max_age}"


def apply_common_headers(
    response: flask.Response,
    *,
    path: str,
    api_prefix: str,
    cache_rules: list[CacheRule] | tuple[CacheRule, ...] = (),
    html_content_security_policy: str | None = None,
    metrics_path_fragment: str = "/metrics",
    ogp_image_path_fragment: str = "/ogp-image/",
    default_api_max_age: int = 600,
    enable_hsts: bool = True,
) -> flask.Response:
    """Apply common cache and security headers to a Flask response."""
    cache_control = _resolve_cache_control(
        path=path,
        api_prefix=api_prefix,
        cache_rules=cache_rules,
        default_max_age=default_api_max_age,
    )
    if cache_control:
        response.headers["Cache-Control"] = cache_control

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Vary"] = "Accept-Encoding"

    if enable_hsts:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    if (path.startswith(api_prefix) or metrics_path_fragment in path) and ogp_image_path_fragment not in path:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"

    content_type = response.headers.get("Content-Type", "")
    if html_content_security_policy and "text/html" in content_type:
        response.headers["Content-Security-Policy"] = html_content_security_policy

    return response
