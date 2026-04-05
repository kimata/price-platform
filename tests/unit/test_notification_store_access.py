from __future__ import annotations

from pathlib import Path

import price_platform.notification
import price_platform.notification._notification_store_types


class _NotificationConfigStub:
    def __init__(self, enabled: bool, db_path: Path) -> None:
        self.enabled = enabled
        self.db_path = db_path


class _ConfigStub:
    def __init__(self, enabled: bool, db_path: Path) -> None:
        self.notification = _NotificationConfigStub(enabled, db_path)

    def get_absolute_path(self, relative_path: Path) -> Path:
        return relative_path


def test_open_existing_notification_store_returns_none_when_disabled(tmp_path: Path) -> None:
    config = _ConfigStub(False, tmp_path / "notification.db")

    assert price_platform.notification.open_existing_notification_store(config) is None


def test_open_existing_notification_store_returns_none_when_db_missing(tmp_path: Path) -> None:
    config = _ConfigStub(True, tmp_path / "notification.db")

    assert price_platform.notification.open_existing_notification_store(config) is None


def _check_protocol_conformance() -> None:
    """型チェッカーが Protocol 適合性を検証する."""
    _: price_platform.notification._notification_store_types.SupportsNotificationStoreConfig = _ConfigStub(
        True, Path("x")
    )
