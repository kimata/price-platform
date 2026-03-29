"""Password hashing helpers for price-platform authentication."""

from __future__ import annotations

import argon2

_HASHER = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def generate_hash(password: str) -> str:
    """Generate an Argon2id hash from a plaintext password."""
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    try:
        _HASHER.verify(password_hash, password)
        return True
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.InvalidHashError:
        return False
