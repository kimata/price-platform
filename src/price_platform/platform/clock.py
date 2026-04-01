"""Thin time facade over my_lib."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import my_lib.platform.time


def get_tz() -> str:
    return my_lib.platform.time.get_tz()


def get_zoneinfo() -> ZoneInfo:
    return my_lib.platform.time.get_zoneinfo()


def now() -> datetime:
    return my_lib.platform.time.now()
