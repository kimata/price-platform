"""Shared SQLite store base classes and migration primitives."""

from __future__ import annotations

import collections.abc
import hashlib
import logging
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .platform import clock
from .platform import sqlite as platform_sqlite

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

    def planned_names(self) -> tuple[str, ...]:
        return tuple(migration.name for migration in self._migrations)

    def pending_names(self, conn: sqlite3.Connection) -> tuple[str, ...]:
        self._ensure_tracking_table(conn)
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        return tuple(migration.name for migration in self._migrations if migration.name not in applied)

    def apply(self, conn: sqlite3.Connection) -> tuple[str, ...]:
        self._ensure_tracking_table(conn)
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        applied_now: list[str] = []
        for migration in self._migrations:
            if migration.name in applied:
                continue
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (migration.name, clock.now().isoformat()),
            )
            logger.info("Applied migration %s", migration.name)
            applied_now.append(migration.name)
        return tuple(applied_now)

    @staticmethod
    def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )


@dataclass(frozen=True)
class SchemaMetadata:
    name: str
    source_path: Path

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source_path.read_bytes()).hexdigest()


class SQLiteBootstrapper:
    """Bootstrap schema and migrations for a SQLite database."""

    def __init__(
        self,
        *,
        db_path: Path,
        schema_path: Path,
        locking_mode: platform_sqlite.LockingMode,
        migrations: Sequence[Migration],
    ) -> None:
        self._db_path = db_path
        self._schema_path = schema_path
        self._locking_mode: platform_sqlite.LockingMode = locking_mode
        self._migration_runner = MigrationRunner(migrations)
        self._schema_metadata = SchemaMetadata(name=schema_path.name, source_path=schema_path)

    def ensure_ready(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self._schema_path}")
        platform_sqlite.init_schema_from_file(
            self._db_path,
            self._schema_path,
            locking_mode=self._locking_mode,
        )
        with platform_sqlite.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            self._record_schema_metadata(conn)
            self._migration_runner.apply(conn)

    @property
    def schema_metadata(self) -> SchemaMetadata:
        return self._schema_metadata

    @property
    def db_path(self) -> Path:
        return self._db_path

    def pending_migrations(self) -> tuple[str, ...]:
        if not self._db_path.exists():
            return self._migration_runner.planned_names()
        with platform_sqlite.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            return self._migration_runner.pending_names(conn)

    def _record_schema_metadata(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        existing_name = conn.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_name'"
        ).fetchone()
        if existing_name is not None and existing_name[0] != self._schema_metadata.name:
            raise RuntimeError(
                f"Schema metadata mismatch: existing={existing_name[0]} current={self._schema_metadata.name}"
            )

        for key, value in (
            ("schema_name", self._schema_metadata.name),
            ("schema_sha256", self._schema_metadata.sha256),
            ("schema_path", str(self._schema_metadata.source_path)),
        ):
            conn.execute(
                """
                INSERT INTO schema_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
        conn.commit()


class SQLiteStoreBase:
    """Shared base for SQLite-backed stores."""

    def __init__(
        self,
        *,
        db_path: Path,
        schema_path: Path,
        locking_mode: platform_sqlite.LockingMode = "NORMAL",
        migrations: Sequence[Migration] = (),
        auto_initialize: bool = True,
    ) -> None:
        self._db_path = db_path
        self._schema_path = schema_path
        self._locking_mode: platform_sqlite.LockingMode = locking_mode
        self._bootstrapper = SQLiteBootstrapper(
            db_path=db_path,
            schema_path=schema_path,
            locking_mode=locking_mode,
            migrations=migrations,
        )
        if auto_initialize:
            self.initialize()

    def initialize(self) -> None:
        self._bootstrapper.ensure_ready()

    @contextmanager
    def connection(self) -> collections.abc.Iterator[sqlite3.Connection]:
        with platform_sqlite.connect(self._db_path, locking_mode=self._locking_mode) as conn:
            conn.row_factory = sqlite3.Row
            yield conn
