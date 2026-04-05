"""通知マネージャーの共通契約テスト補助。"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock


def build_disabled_notification_config_mock() -> MagicMock:
    """通知無効の設定モックを作る。"""
    config = MagicMock()
    config.notification.enabled = False
    config.notification.twitter.enabled = False
    config.webapp.external_url = ""
    return config


def build_enabled_notification_config_mock() -> MagicMock:
    """通知有効の設定モックを作る。"""
    config = MagicMock()
    config.notification.enabled = True
    config.notification.db_path = "data/notification.db"
    config.notification.twitter.enabled = False
    config.notification.webpush.enabled = False
    config.notification.webpush.db_path = "data/webpush.db"
    config.schema_dir = MagicMock()
    config.get_absolute_path.return_value = MagicMock()
    config.webapp.external_url = "https://example.com/"
    return config


def verify_notification_manager_basic_contract(
    manager_factory: Callable[[MagicMock], object],
) -> None:
    """通知マネージャーの基本挙動を検証する。"""
    manager = manager_factory(build_disabled_notification_config_mock())
    manager.start(lambda: MagicMock())
    assert not manager.is_running
    assert manager.store is None

    manager = manager_factory(build_disabled_notification_config_mock())
    manager.stop()

    manager = manager_factory(build_disabled_notification_config_mock())
    manager.enqueue(MagicMock())

    manager = manager_factory(build_disabled_notification_config_mock())
    assert not manager.is_running


def verify_notification_manager_factory_contract(
    init_manager: Callable[[MagicMock], object],
) -> None:
    """ファクトリが毎回新しいインスタンスを返すことを検証する。"""
    config = build_disabled_notification_config_mock()
    first = init_manager(config)
    second = init_manager(config)

    assert type(first) is type(second)
    assert first is not second
