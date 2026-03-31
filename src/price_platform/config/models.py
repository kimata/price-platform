"""Configuration models for price-platform applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import warnings


def _resolve_path(value: str | Path, *, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


@dataclass(frozen=True)
class AmazonStoreConfig:
    """Amazon API credentials."""

    credential_id: str
    credential_secret: str
    associate: str
    version: str = "3.3"

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "AmazonStoreConfig":
        return cls(
            credential_id=data["credential_id"],
            credential_secret=data["credential_secret"],
            associate=data["associate"],
            version=data.get("version", "3.3"),
        )


@dataclass(frozen=True)
class RakutenStoreConfig:
    """Rakuten API credentials."""

    application_id: str
    affiliate_id: str | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "RakutenStoreConfig":
        return cls(
            application_id=data["application_id"],
            affiliate_id=data.get("affiliate_id"),
        )


@dataclass(frozen=True)
class YahooStoreConfig:
    """Yahoo Shopping API credentials."""

    client_id: str
    secret: str
    affiliate_type: str | None = None
    affiliate_id: str | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "YahooStoreConfig":
        return cls(
            client_id=data["client_id"],
            secret=data["secret"],
            affiliate_type=data.get("affiliate_type"),
            affiliate_id=data.get("affiliate_id"),
        )


@dataclass(frozen=True)
class MercariConfig:
    """Mercari affiliate configuration."""

    affiliate_id: str = ""

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> MercariConfig:
        if data is None:
            return cls()
        return cls(**data)


@dataclass(frozen=True)
class StoreConfig:
    """Store API credentials used by price applications."""

    amazon: AmazonStoreConfig
    yahoo: YahooStoreConfig
    rakuten: RakutenStoreConfig
    mercari: MercariConfig = field(default_factory=MercariConfig)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> StoreConfig:
        return cls(
            amazon=AmazonStoreConfig.parse(data["amazon"]),
            yahoo=YahooStoreConfig.parse(data["yahoo"]),
            rakuten=RakutenStoreConfig.parse(data["rakuten"]),
            mercari=MercariConfig.parse(data.get("mercari")),
        )


@dataclass(frozen=True)
class ScrapeConfig:
    """Scraping configuration."""

    stores: tuple[str, ...] = field(default_factory=tuple)
    max_items: int = 20
    batch_size: int = 10
    shuffle_products: bool = True

    @classmethod
    def parse(cls, data: dict[str, Any]) -> ScrapeConfig:
        stores = data.get("stores", ())
        return cls(
            stores=tuple(stores),
            max_items=data.get("max_items", 20),
            batch_size=data.get("batch_size", 10),
            shuffle_products=data.get("shuffle_products", True),
        )


@dataclass(frozen=True)
class SeleniumConfig:
    """Selenium WebDriver configuration."""

    data_path: Path = Path("data/selenium")
    headless: bool = True

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> SeleniumConfig:
        return cls(
            data_path=_resolve_path(data.get("data_path", "data/selenium"), base_dir=base_dir),
            headless=data.get("headless", True),
        )


@dataclass(frozen=True)
class DatabaseConfig:
    """Database configuration."""

    path: Path = Path("data/price.db")

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> DatabaseConfig:
        return cls(path=_resolve_path(data.get("path", "data/price.db"), base_dir=base_dir))


@dataclass(frozen=True)
class WebAppDataConfig:
    """Runtime data paths for web applications."""

    schedule_file_path: Path | None = None
    log_file_path: Path | None = None
    stat_dir_path: Path | None = None

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> WebAppDataConfig:
        return cls(
            schedule_file_path=_resolve_path(data["schedule_file_path"], base_dir=base_dir)
            if "schedule_file_path" in data
            else None,
            log_file_path=_resolve_path(data["log_file_path"], base_dir=base_dir)
            if "log_file_path" in data
            else None,
            stat_dir_path=_resolve_path(data["stat_dir_path"], base_dir=base_dir) if "stat_dir_path" in data else None,
        )


@dataclass(frozen=True)
class WebAppConfig:
    """Web application configuration."""

    external_url: str | None = None
    static_dir_path: Path | None = None
    data: WebAppDataConfig | None = None

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> WebAppConfig:
        return cls(
            external_url=data.get("external_url"),
            static_dir_path=_resolve_path(data["static_dir_path"], base_dir=base_dir)
            if "static_dir_path" in data
            else None,
            data=WebAppDataConfig.parse(data["data"], base_dir=base_dir) if "data" in data else None,
        )


@dataclass(frozen=True)
class MetricsAuthConfig:
    """Metrics authentication configuration."""

    enabled: bool = False
    password_hash: str = ""
    jwt_secret_path: Path = Path("data/jwt_secret.key")
    jwt_expiry_hours: int = 24

    @classmethod
    def parse(cls, data: dict[str, Any] | None, *, base_dir: Path) -> MetricsAuthConfig:
        if data is None:
            return cls(jwt_secret_path=_resolve_path("data/jwt_secret.key", base_dir=base_dir))
        return cls(
            enabled=data.get("enabled", False),
            password_hash=data.get("password_hash", ""),
            jwt_secret_path=_resolve_path(data.get("jwt_secret_path", "data/jwt_secret.key"), base_dir=base_dir),
            jwt_expiry_hours=data.get("jwt_expiry_hours", 24),
        )


@dataclass(frozen=True)
class MetricsConfig:
    """Metrics collection configuration."""

    enabled: bool = True
    db_path: Path = Path("data/metrics.db")
    auth: MetricsAuthConfig = field(default_factory=MetricsAuthConfig)

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> MetricsConfig:
        return cls(
            enabled=data.get("enabled", True),
            db_path=_resolve_path(data.get("db_path", "data/metrics.db"), base_dir=base_dir),
            auth=MetricsAuthConfig.parse(data.get("auth"), base_dir=base_dir),
        )


@dataclass(frozen=True)
class CacheConfig:
    """Cache configuration."""

    path: Path

    @classmethod
    def parse(cls, data: dict[str, Any], *, base_dir: Path) -> CacheConfig:
        return cls(path=_resolve_path(data["path"], base_dir=base_dir))


@dataclass(frozen=True)
class LivenessFileConfig:
    """Liveness file configuration."""

    crawler: Path

    @classmethod
    def parse(
        cls,
        data: dict[str, Any] | str,
        *,
        default_file: Path,
        base_dir: Path,
    ) -> LivenessFileConfig:
        if isinstance(data, str):
            return cls(crawler=_resolve_path(data, base_dir=base_dir))
        return cls(crawler=_resolve_path(data.get("crawler", default_file), base_dir=base_dir))


@dataclass(frozen=True)
class LivenessConfig:
    """Liveness configuration."""

    file: LivenessFileConfig
    interval_sec: int = 300

    @classmethod
    def parse(cls, data: dict[str, Any], *, default_file: Path, base_dir: Path) -> LivenessConfig:
        file_data = data.get("file", {"crawler": str(default_file)})
        return cls(
            file=LivenessFileConfig.parse(file_data, default_file=default_file, base_dir=base_dir),
            interval_sec=data.get("interval_sec", 300),
        )


@dataclass(frozen=True)
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
        if data is None:
            return cls()
        return cls(**data)


@dataclass(frozen=True)
class WebPushConfig:
    """Web Push notification configuration."""

    enabled: bool = False
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_contact: str = ""
    db_path: Path = Path("data/webpush.db")

    @classmethod
    def parse(cls, data: dict[str, Any] | None, *, base_dir: Path) -> WebPushConfig:
        if data is None:
            return cls(db_path=_resolve_path("data/webpush.db", base_dir=base_dir))
        return cls(
            enabled=data.get("enabled", False),
            vapid_private_key=data.get("vapid_private_key", ""),
            vapid_public_key=data.get("vapid_public_key", ""),
            vapid_contact=data.get("vapid_contact", ""),
            db_path=_resolve_path(data.get("db_path", "data/webpush.db"), base_dir=base_dir),
        )


@dataclass(frozen=True)
class NotificationConfig:
    """Notification configuration."""

    enabled: bool = False
    db_path: Path = Path("data/notification.db")
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    webpush: WebPushConfig = field(default_factory=WebPushConfig)

    @classmethod
    def parse(cls, data: dict[str, Any] | None, *, base_dir: Path) -> NotificationConfig:
        if data is None:
            return cls(
                db_path=_resolve_path("data/notification.db", base_dir=base_dir),
                webpush=WebPushConfig.parse(None, base_dir=base_dir),
            )
        return cls(
            enabled=data.get("enabled", False),
            db_path=_resolve_path(data.get("db_path", "data/notification.db"), base_dir=base_dir),
            twitter=TwitterConfig.parse(data.get("twitter")),
            webpush=WebPushConfig.parse(data.get("webpush"), base_dir=base_dir),
        )


@dataclass(frozen=True)
class ClientMetricsConfig:
    """Client-side performance metrics configuration."""

    enabled: bool = False
    db_path: Path = Path("data/client_metrics.db")
    sampling_rate: float = 1.0
    retention_days: int = 7

    @classmethod
    def parse(cls, data: dict[str, Any] | None, *, base_dir: Path) -> ClientMetricsConfig:
        if data is None:
            return cls(db_path=_resolve_path("data/client_metrics.db", base_dir=base_dir))
        return cls(
            enabled=data.get("enabled", False),
            db_path=_resolve_path(data.get("db_path", "data/client_metrics.db"), base_dir=base_dir),
            sampling_rate=data.get("sampling_rate", 1.0),
            retention_days=data.get("retention_days", 7),
        )


@dataclass
class AppConfig:
    """Shared application configuration."""

    scrape: ScrapeConfig
    store: StoreConfig
    selenium: SeleniumConfig
    database: DatabaseConfig
    webapp: WebAppConfig
    metrics: MetricsConfig
    liveness: LivenessConfig
    product_catalog_path: Path
    cache: CacheConfig
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    client_metrics: ClientMetricsConfig = field(default_factory=ClientMetricsConfig)
    _base_dir: Path = field(default_factory=Path.cwd, repr=False)

    def get_absolute_path(self, relative_path: Path) -> Path:
        path = relative_path
        if path.is_absolute():
            return path
        return self._base_dir / path

    @property
    def schema_dir(self) -> Path:
        warnings.warn(
            "AppConfig.schema_dir is deprecated; bundled price-platform schemas are the default owner.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._base_dir / "schema"

    @property
    def absolute_cache_path(self) -> Path:
        return self.get_absolute_path(self.cache.path)
