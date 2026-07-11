"""price-platform Web アプリ向けの CORS ヘルパー。"""

from __future__ import annotations

import ipaddress
import os
import urllib.parse

# ローカル/プライベート origin を無条件に許可するためのオプトインフラグ (CI / E2E 用)。
# Origin ヘッダは非ブラウザクライアントが任意に設定できるため、
# 本番で常時有効にすると同一オリジン保護が偽装でバイパスされる (B2)。
ALLOW_LOCAL_ORIGIN_ENV = "PRICE_PLATFORM_ALLOW_LOCAL_ORIGIN"


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


def _local_origin_bypass_enabled() -> bool:
    return os.environ.get(ALLOW_LOCAL_ORIGIN_ENV, "").strip().lower() in ("1", "true", "yes")


def is_allowed_request_origin(
    *,
    allowed_origins: list[str] | tuple[str, ...],
    origin: str | None,
    referer: str | None,
    allow_local_origins: bool | None = None,
) -> bool:
    """Return whether a request origin or referer matches the allowed origin list.

    localhost / private-IP origin の無条件許可は、環境変数
    PRICE_PLATFORM_ALLOW_LOCAL_ORIGIN (または allow_local_origins 引数) で
    明示的に有効化した場合のみ適用する (CI / E2E 環境向け)。
    デフォルト無効。恒久バイパスにすると Origin ヘッダ偽装で
    同一オリジン保護が素通りになるため。
    """
    if origin and origin in allowed_origins:
        return True

    if allow_local_origins is None:
        allow_local_origins = _local_origin_bypass_enabled()
    if allow_local_origins and origin and _is_local_origin(origin):
        return True

    referer_origin = extract_origin(referer)
    return referer_origin in allowed_origins if referer_origin else False
