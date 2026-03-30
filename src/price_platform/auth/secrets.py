"""Secret loading helpers for price-platform applications."""

from __future__ import annotations

import os
import pathlib
import secrets
import threading
from typing import Protocol


class SecretStore(Protocol):
    """Protocol for secret persistence implementations."""

    def load(self) -> str:
        """Load an existing secret."""

    def ensure(self) -> str:
        """Load a secret or create it on first use."""


class FileSecretStore:
    """Thread-safe file-backed secret store."""

    def __init__(self, path: pathlib.Path):
        self._path = path
        self._lock = threading.Lock()
        self._cached_secret: str | None = None

    def load(self) -> str:
        """Load an existing secret value from disk."""
        if self._cached_secret is not None:
            return self._cached_secret

        with self._lock:
            if self._cached_secret is not None:
                return self._cached_secret
            if not self._path.exists():
                msg = f"Secret file not found: {self._path}"
                raise FileNotFoundError(msg)
            self._cached_secret = self._path.read_text(encoding="utf-8").strip()
            return self._cached_secret

    def create(self) -> str:
        """Create a new secret file and return the generated value."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            secret_value = secrets.token_urlsafe(64)
            self._path.write_text(secret_value, encoding="utf-8")
            os.chmod(self._path, 0o600)
            self._cached_secret = secret_value
            return secret_value

    def ensure(self) -> str:
        """Load a secret value or create it when it does not exist."""
        try:
            return self.load()
        except FileNotFoundError:
            return self.create()
