from __future__ import annotations

from pathlib import Path

import price_platform.auth.password_hash
import price_platform.auth.rate_limiter
import price_platform.auth.secrets


def test_file_secret_store_load_create_and_ensure(tmp_path: Path) -> None:
    secret_path = tmp_path / "secret.key"
    store = price_platform.auth.secrets.FileSecretStore(secret_path)

    created = store.ensure()

    assert secret_path.exists()
    assert store.load() == created
    assert store.ensure() == created


def test_file_secret_store_load_missing_raises(tmp_path: Path) -> None:
    store = price_platform.auth.secrets.FileSecretStore(tmp_path / "missing.key")

    try:
        store.load()
    except FileNotFoundError as exc:
        assert "Secret file not found" in str(exc)
    else:
        raise AssertionError("FileSecretStore.load() should raise for missing files")


def test_file_secret_store_shared_lock_across_instances(tmp_path: Path) -> None:
    """同じパスを指す複数インスタンスが同一ロックを共有することを確認"""
    secret_path = tmp_path / "shared.key"
    store_a = price_platform.auth.secrets.FileSecretStore(secret_path)
    store_b = price_platform.auth.secrets.FileSecretStore(secret_path)

    lock_a = price_platform.auth.secrets.FileSecretStore._lock_for(store_a._path)
    lock_b = price_platform.auth.secrets.FileSecretStore._lock_for(store_b._path)
    assert lock_a is lock_b


def test_file_secret_store_concurrent_ensure(tmp_path: Path) -> None:
    """複数スレッドから同時に ensure() しても同一シークレットが返ることを確認"""
    import concurrent.futures

    secret_path = tmp_path / "race.key"
    num_threads = 20

    def call_ensure() -> str:
        store = price_platform.auth.secrets.FileSecretStore(secret_path)
        return store.ensure()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(call_ensure) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert len(set(results)) == 1, f"Expected single secret, got {len(set(results))} distinct values"


def test_in_memory_rate_limiter_lockout_and_clear() -> None:
    current_time = 1_000.0

    def now_fn() -> float:
        return current_time

    limiter = price_platform.auth.rate_limiter.InMemoryRateLimiter(
        price_platform.auth.rate_limiter.RateLimitSettings(
            failure_window_sec=60,
            max_failures=2,
            lockout_duration_sec=120,
        ),
        now_fn=now_fn,
    )

    assert limiter.record_failure("127.0.0.1") is False
    assert limiter.record_failure("127.0.0.1") is True
    assert limiter.is_locked_out("127.0.0.1") is True
    assert limiter.get_lockout_remaining_sec("127.0.0.1") == 120

    limiter.clear_failures("127.0.0.1")

    assert limiter.is_locked_out("127.0.0.1") is False
    assert limiter.get_lockout_remaining_sec("127.0.0.1") == 0


def test_password_hash_roundtrip_and_invalid_hash() -> None:
    password_hash = price_platform.auth.password_hash.generate_hash("s3cret")

    assert price_platform.auth.password_hash.verify_password("s3cret", password_hash) is True
    assert price_platform.auth.password_hash.verify_password("wrong", password_hash) is False
    assert price_platform.auth.password_hash.verify_password("s3cret", "invalid-hash") is False
