"""Secret loading helpers for price-platform applications."""

from __future__ import annotations

import pathlib
import secrets
import threading


class FileSecretProvider:
    """Thread-safe file backed secret provider."""

    def __init__(self, path: str | pathlib.Path, *, allow_generate: bool = True):
        self._path = pathlib.Path(path)
        self._allow_generate = allow_generate
        self._lock = threading.Lock()
        self._cached_secret: str | None = None

    def get_secret(self) -> str:
        """Return the secret value, creating it on first access if allowed."""
        if self._cached_secret is not None:
            return self._cached_secret

        with self._lock:
            if self._cached_secret is not None:
                return self._cached_secret

            if self._path.exists():
                self._cached_secret = self._path.read_text(encoding="utf-8").strip()
                return self._cached_secret

            if not self._allow_generate:
                msg = f"Secret file not found: {self._path}"
                raise FileNotFoundError(msg)

            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._cached_secret = secrets.token_urlsafe(64)
            self._path.write_text(self._cached_secret, encoding="utf-8")
            return self._cached_secret
