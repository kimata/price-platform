"""SQLite migration definitions owned by price-platform."""

from .client_metrics import build_client_metrics_migrations

__all__ = [
    "build_client_metrics_migrations",
]
