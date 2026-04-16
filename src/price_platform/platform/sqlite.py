"""SQLite ヘルパーの薄い集約層。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

import my_lib.sqlite_util

LockingMode = Literal["NORMAL", "EXCLUSIVE"]
DatabaseConnection = my_lib.sqlite_util.DatabaseConnection


def connect(
    db_path: str | Path,
    *,
    timeout: float = 60.0,
    locking_mode: LockingMode | None = None,
) -> DatabaseConnection:
    return my_lib.sqlite_util.connect(db_path, timeout=timeout, locking_mode=locking_mode)


def init_schema_from_file(
    db_path: str | Path,
    schema_path: str | Path,
    *,
    timeout: float = 60.0,
    locking_mode: LockingMode | None = None,
) -> None:
    my_lib.sqlite_util.init_schema_from_file(
        db_path,
        schema_path,
        timeout=timeout,
        locking_mode=locking_mode,
    )


def recover(db_path: str | Path) -> None:
    my_lib.sqlite_util.recover(db_path)


def exec_schema_from_file(conn: sqlite3.Connection, schema_path: str | Path) -> None:
    my_lib.sqlite_util.exec_schema_from_file(conn, schema_path)
