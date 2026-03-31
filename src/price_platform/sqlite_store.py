"""Shared SQLite store base classes and migration primitives."""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .platform import clock, sqlite as platform_sqlite

logger = logging.getLogger(__name__)

MigrationFn = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    name: str
    apply: MigrationFn


class MigrationRunner:
    """Apply named SQLite migrations once per database."""

    def __init__(self, migrations: Sequence[Migration]):
        self._migrations = tuple(migrations)

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        for migration in self._migrations:
            if migration.name in applied:
                continue
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (migration.name, clock.now().isoformat()),
            )
            logger.info("Applied migration %s", migration.name)


class SQLiteStoreBase:
    """Shared base for SQLite-backed stores."""

    def __init__(
        self,
        *,
        db_path: Path,
        schema_path: Path,
        locking_mode: platform_sqlite.LockingMode = "NORMAL",
        migrations: Sequence[Migration] = (),
    ) -> None:
        self._db_path = db_path
        self._schema_path = schema_path
        self._locking_mode = locking_mode
        self._migration_runner = MigrationRunner(migrations)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self._schema_path}")
        platform_sqlite.init_schema_from_file(
            self._db_path,
            self._schema_path,
            locking_mode=self._locking_mode,
        )
        with self.connection() as conn:
            self._migration_runner.apply(conn)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        with platform_sqlite.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            yield conn
