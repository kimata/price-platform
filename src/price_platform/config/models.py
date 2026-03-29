"""Configuration models for price-platform applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import my_lib.store.amazon.config
import my_lib.store.rakuten.config
import my_lib.store.yahoo.config
import my_lib.webapp.config


@dataclass
class MercariConfig:
    """Mercari affiliate configuration."""

    affiliate_id: str = ""

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> MercariConfig:
        """Parse Mercari config from dict."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass
class StoreConfig:
    """Store API configuration."""

    amazon: my_lib.store.amazon.config.AmazonApiConfig
    yahoo: my_lib.store.yahoo.config.YahooApiConfig
    rakuten: my_lib.store.rakuten.config.RakutenApiConfig
    mercari: MercariConfig = field(default_factory=MercariConfig)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> StoreConfig:
        """Parse store config from dict."""
        return cls(
            amazon=my_lib.store.amazon.config.AmazonApiConfig.parse(data["amazon"]),
            yahoo=my_lib.store.yahoo.config.YahooApiConfig.parse(data["yahoo"]),
            rakuten=my_lib.store.rakuten.config.RakutenApiConfig.parse(data["rakuten"]),
            mercari=MercariConfig.parse(data.get("mercari")),
        )


@dataclass
class ScrapeConfig:
    """Scraping configuration."""

    stores: list[str] = field(default_factory=list)
    max_items: int = 20
    batch_size: int = 10
    shuffle_products: bool = True

    @classmethod
    def parse(cls, data: dict[str, Any]) -> ScrapeConfig:
        """Parse scrape config from dict."""
        return cls(**data)


@dataclass
class SeleniumConfig:
    """Selenium WebDriver configuration."""

    data_path: str = "data/selenium"
    headless: bool = True


@dataclass
class DatabaseConfig:
    """Database configuration."""

    path: str = "data/price.db"


@dataclass
class MetricsAuthConfig:
    """Metrics authentication configuration."""

    enabled: bool = False
    password_hash: str = ""
    jwt_secret_path: str = "data/jwt_secret.key"  # noqa: S105
    jwt_expiry_hours: int = 24

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> MetricsAuthConfig:
        """Parse metrics auth config from dict."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass
class MetricsConfig:
    """Metrics collection configuration."""

    enabled: bool = True
    db_path: str = "data/metrics.db"
    auth: MetricsAuthConfig = field(default_factory=MetricsAuthConfig)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> MetricsConfig:
        """Parse metrics config from dict."""
        parsed = dict(data)
        parsed["auth"] = MetricsAuthConfig.parse(parsed.get("auth"))
        return cls(**parsed)


@dataclass
class CacheConfig:
    """Cache configuration."""

    path: Path

    @classmethod
    def parse(cls, data: dict[str, Any]) -> CacheConfig:
        """Parse cache config from dict."""
        return cls(path=Path(data["path"]))


@dataclass
class LivenessFileConfig:
    """Liveness file configuration."""

    crawler: Path

    @classmethod
    def parse(cls, data: dict[str, Any] | str, *, default_file: Path) -> LivenessFileConfig:
        """Parse liveness file config from dict or string."""
        if isinstance(data, str):
            return cls(crawler=Path(data))
        return cls(crawler=Path(data.get("crawler", default_file)))


@dataclass
class LivenessConfig:
    """Liveness configuration."""

    file: LivenessFileConfig
    interval_sec: int = 300

    @classmethod
    def parse(cls, data: dict[str, Any], *, default_file: Path) -> LivenessConfig:
        """Parse liveness config from dict."""
        file_data = data.get("file", {"crawler": str(default_file)})
        return cls(
            file=LivenessFileConfig.parse(file_data, default_file=default_file),
            interval_sec=data.get("interval_sec", 300),
        )


@dataclass
class TwitterConfig:
    """Twitter API configuration."""

    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    access_token_secret: str = ""
    post_interval_sec: int = 300

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> TwitterConfig:
        """Parse Twitter config from dict."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass
class WebPushConfig:
    """Web Push notification configuration."""

    enabled: bool = False
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_contact: str = ""
    db_path: str = "data/webpush.db"

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> WebPushConfig:
        """Parse Web Push config from dict."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass
class NotificationConfig:
    """Notification configuration."""

    enabled: bool = False
    db_path: str = "data/notification.db"
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    webpush: WebPushConfig = field(default_factory=WebPushConfig)

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> NotificationConfig:
        """Parse notification config from dict."""
        if data is None:
            return cls()
        parsed = dict(data)
        parsed["twitter"] = TwitterConfig.parse(parsed.get("twitter"))
        parsed["webpush"] = WebPushConfig.parse(parsed.get("webpush"))
        return cls(**parsed)


@dataclass
class ClientMetricsConfig:
    """Client-side performance metrics configuration."""

    enabled: bool = False
    db_path: str = "data/client_metrics.db"
    sampling_rate: float = 1.0
    retention_days: int = 7

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> ClientMetricsConfig:
        """Parse client metrics config from dict."""
        if data is None:
            return cls()
        return cls(**data)


@dataclass
class AppConfig:
    """Shared application configuration."""

    scrape: ScrapeConfig
    store: StoreConfig
    selenium: SeleniumConfig
    database: DatabaseConfig
    webapp: my_lib.webapp.config.WebappConfig
    metrics: MetricsConfig
    liveness: LivenessConfig
    product_catalog_path: str
    cache: CacheConfig
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    client_metrics: ClientMetricsConfig = field(default_factory=ClientMetricsConfig)
    _base_dir: Path = field(default_factory=Path.cwd, repr=False)

    def get_absolute_path(self, relative_path: str) -> Path:
        """Get absolute path from a config-relative path."""
        return self._base_dir / relative_path

    @property
    def schema_dir(self) -> Path:
        """Get absolute schema directory path."""
        return self._base_dir / "schema"

    @property
    def absolute_cache_path(self) -> Path:
        """Get absolute cache directory path."""
        return self._base_dir / self.cache.path
