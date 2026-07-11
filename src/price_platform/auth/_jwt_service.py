"""JWT の発行・検証の共通ヘルパ。

api_token / metrics_auth の 2 系統で重複していた
「FileSecretStore で秘密をロード → jwt.encode/decode → 例外で None」の
ロジックを一箇所に集約する (R3)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt

from .secrets import FileSecretStore

JWT_ALGORITHM = "HS256"

# jwt ライブラリ由来のデコード済みクレーム。構造は JWT 標準に従うため dict のまま扱う。
TokenPayload = dict[str, Any]


def encode_token(secret_path: Path, *, claims: dict[str, Any], lifetime: timedelta) -> str:
    """iat / exp を付与して JWT を発行する。秘密が無ければ生成する。"""
    secret = FileSecretStore(secret_path).ensure()
    now = datetime.now(UTC)
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_token(
    secret_path: Path,
    token: str,
    *,
    expected_type: str | None = None,
) -> TokenPayload | None:
    """JWT を検証してペイロードを返す。無効・期限切れ・type 不一致は None。"""
    try:
        secret = FileSecretStore(secret_path).load()
    except FileNotFoundError:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        # ExpiredSignatureError も InvalidTokenError のサブクラス
        return None
    if expected_type is not None and payload.get("type") != expected_type:
        return None
    return dict(payload)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Authorization ヘッダから Bearer トークンを取り出す。"""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    return authorization_header.removeprefix("Bearer ")
