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
        ...

    def ensure(self) -> str:
        """Load a secret or create it on first use."""
        ...


class FileSecretStore:
    """Thread-safe file-backed secret store.

    Synchronisation is per resolved path: all instances that point to the
    same file share one ``threading.Lock``, so concurrent ``ensure()``
    calls in a threaded Flask server never race on secret creation.

    Creation uses ``O_CREAT | O_EXCL`` so that only the first writer
    wins even across processes.
    """

    _class_lock = threading.Lock()
    _path_locks: dict[pathlib.Path, threading.Lock] = {}
    _cache: dict[pathlib.Path, str] = {}

    def __init__(self, path: pathlib.Path):
        self._path = path.resolve()

    @classmethod
    def _lock_for(cls, path: pathlib.Path) -> threading.Lock:
        """Return a shared lock for *path*, creating one if needed."""
        with cls._class_lock:
            if path not in cls._path_locks:
                cls._path_locks[path] = threading.Lock()
            return cls._path_locks[path]

    def load(self) -> str:
        """Load an existing secret value from disk."""
        cached = self._cache.get(self._path)
        if cached is not None:
            return cached

        lock = self._lock_for(self._path)
        with lock:
            cached = self._cache.get(self._path)
            if cached is not None:
                return cached
            if not self._path.exists():
                msg = f"Secret file not found: {self._path}"
                raise FileNotFoundError(msg)
            secret = self._path.read_text(encoding="utf-8").strip()
            self._cache[self._path] = secret
            return secret

    def _atomic_create(self) -> str:
        """Create a new secret file atomically.

        Uses ``O_CREAT | O_EXCL`` so that only one writer succeeds when
        multiple processes race.  If the file already exists (another
        process won), fall back to reading.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        secret_value = secrets.token_urlsafe(64)
        try:
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            secret = self._path.read_text(encoding="utf-8").strip()
            self._cache[self._path] = secret
            return secret
        try:
            os.write(fd, secret_value.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache[self._path] = secret_value
        return secret_value

    def ensure(self) -> str:
        """Load a secret value or create it when it does not exist.

        Single critical section: check cache → check file → atomic create.
        """
        cached = self._cache.get(self._path)
        if cached is not None:
            return cached

        lock = self._lock_for(self._path)
        with lock:
            cached = self._cache.get(self._path)
            if cached is not None:
                return cached
            if self._path.exists():
                secret = self._path.read_text(encoding="utf-8").strip()
                self._cache[self._path] = secret
                return secret
            return self._atomic_create()
