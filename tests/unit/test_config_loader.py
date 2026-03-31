from __future__ import annotations

from pathlib import Path

import my_lib.config
import price_platform.config


def _make_config_data() -> dict[str, object]:
    return {
        "scrape": {
            "stores": ["amazon", "rakuten"],
            "max_items": 12,
        },
        "store": {
            "amazon": {
                "credential_id": "amazon-id",
                "credential_secret": "amazon-secret",
                "associate": "assoc-tag",
            },
            "yahoo": {
                "client_id": "yahoo-client",
                "secret": "yahoo-secret",
            },
            "rakuten": {
                "application_id": "rakuten-app",
                "affiliate_id": "rakuten-aff",
            },
        },
        "selenium": {
            "data_path": "data/selenium",
            "headless": True,
        },
        "database": {
            "path": "data/price.db",
        },
        "webapp": {
            "external_url": "https://example.com",
            "data": {
                "log_file_path": "data/webapp.log",
            },
        },
        "metrics": {
            "enabled": True,
            "db_path": "data/metrics.db",
            "auth": {
                "enabled": True,
                "password_hash": "hash",
                "jwt_secret_path": "data/jwt_secret.key",
            },
        },
        "liveness": {
            "interval_sec": 45,
        },
        "product_catalog_path": "catalog/products.yaml",
        "cache": {
            "path": "cache",
        },
    }


def test_parse_app_config_for_resolves_paths_from_spec() -> None:
    base_dir = Path("/tmp/price-platform-test")
    spec = price_platform.config.AppConfigSpec(
        env_var_name="TEST_CONFIG_ENV",
        default_liveness_file=Path("/dev/shm/test-app/healthz"),
    )

    config = price_platform.config.parse_app_config_for(
        price_platform.config.AppConfig,
        spec,
        _make_config_data(),
        base_dir=base_dir,
    )

    assert config.database.path == base_dir / "data/price.db"
    assert config.metrics.auth.jwt_secret_path == base_dir / "data/jwt_secret.key"
    assert config.product_catalog_path == base_dir / "catalog/products.yaml"
    assert config.liveness.file.crawler == Path("/dev/shm/test-app/healthz")
    assert config.cache.path == base_dir / "cache"


def test_load_app_config_for_reads_env_var(monkeypatch) -> None:
    spec = price_platform.config.AppConfigSpec(
        env_var_name="TEST_CONFIG_ENV",
        default_liveness_file=Path("/dev/shm/test-app/healthz"),
    )

    monkeypatch.setenv(spec.env_var_name, "/tmp/app/config.yaml")
    monkeypatch.setattr(my_lib.config, "load", lambda path: _make_config_data())

    config = price_platform.config.load_app_config_for(price_platform.config.AppConfig, spec)

    assert config._base_dir == Path("/tmp/app")
    assert config.webapp.external_url == "https://example.com"
