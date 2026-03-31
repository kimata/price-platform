from __future__ import annotations

from pathlib import Path

import price_platform.notification


class _NotificationConfigStub:
    def __init__(self, enabled: bool, db_path: Path) -> None:
        self.enabled = enabled
        self.db_path = db_path


class _ConfigStub:
    def __init__(self, enabled: bool, db_path: Path, schema_dir: Path) -> None:
        self.notification = _NotificationConfigStub(enabled, db_path)
        self.schema_dir = schema_dir

    def get_absolute_path(self, relative_path: Path) -> Path:
        return relative_path


def test_open_existing_notification_store_returns_none_when_disabled(tmp_path: Path) -> None:
    config = _ConfigStub(False, tmp_path / "notification.db", tmp_path)

    assert price_platform.notification.open_existing_notification_store(config) is None


def test_open_existing_notification_store_returns_none_when_db_missing(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    config = _ConfigStub(True, tmp_path / "notification.db", schema_dir)

    assert price_platform.notification.open_existing_notification_store(config) is None
