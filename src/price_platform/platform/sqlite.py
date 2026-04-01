"""Thin SQLite facade over my_lib."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Literal

import my_lib.platform.sqlite

LockingMode = Literal["NORMAL", "EXCLUSIVE"]
DatabaseConnection = my_lib.platform.sqlite.DatabaseConnection


def connect(
    db_path: str | Path,
    *,
    timeout: float = 60.0,
    locking_mode: LockingMode | None = None,
) -> DatabaseConnection:
    return my_lib.platform.sqlite.connect(db_path, timeout=timeout, locking_mode=locking_mode)


def init_schema_from_file(
    db_path: str | Path,
    schema_path: str | Path,
    *,
    timeout: float = 60.0,
    locking_mode: LockingMode | None = None,
) -> None:
    my_lib.platform.sqlite.init_schema_from_file(
        db_path,
        schema_path,
        timeout=timeout,
        locking_mode=locking_mode,
    )


def recover(db_path: str | Path) -> None:
    my_lib.platform.sqlite.recover(db_path)


def exec_schema_from_file(conn: sqlite3.Connection, schema_path: str | Path) -> None:
    my_lib.platform.sqlite.exec_schema_from_file(conn, schema_path)
