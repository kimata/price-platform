"""my_lib.notify 境界の facade。"""

from __future__ import annotations

from typing import Any, TypeAlias

import my_lib.notify.slack

SlackConfigTypes: TypeAlias = my_lib.notify.slack.SlackConfigTypes


def parse_slack_config(data: dict[str, Any] | None) -> SlackConfigTypes:
    """config の slack セクションをパースする。未設定なら NullObject を返す。"""
    return my_lib.notify.slack.SlackConfig.parse(data or {})


def empty_slack_config() -> SlackConfigTypes:
    """未設定を表す NullObject 設定を返す。"""
    return my_lib.notify.slack.SlackEmptyConfig()


def error(config: SlackConfigTypes, title: str, message: str) -> None:
    """Slack エラーチャンネルへ通知する（レート制限付き。未設定なら何もしない）。"""
    if isinstance(config, my_lib.notify.slack.SlackCaptchaOnlyConfig):
        # error チャンネル設定を持たない構成では通知しない
        return
    my_lib.notify.slack.error(config, title, message)
