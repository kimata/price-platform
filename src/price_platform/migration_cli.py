"""CLI and helpers for price-platform-owned SQLite schema migrations."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .migrations import (
    CANONICAL_GROUP_FILTER_COLUMN,
    build_client_metrics_migrations,
    build_price_event_migrations,
    build_webpush_migrations,
)
from .platform import sqlite as platform_sqlite
from .schema_registry import resolve_schema_path
from .sqlite_store import Migration, SQLiteBootstrapper


@dataclass(frozen=True)
class MigrationTargetSpec:
    name: str
    schema_name: str

    def build_migrations(self, args: argparse.Namespace) -> tuple[Migration, ...]:
        if self.name == "price_events":
            return build_price_event_migrations(selection_column=args.selection_column)
        if self.name == "client_metrics":
            return build_client_metrics_migrations()
        if self.name == "webpush":
            return build_webpush_migrations(
                group_filter_column=args.group_filter_column,
                legacy_group_filter_columns=tuple(args.legacy_group_filter_column),
                legacy_product_filter_columns=tuple(args.legacy_product_filter_column),
            )
        return ()


@dataclass(frozen=True)
class MigrationStatus:
    target: str
    db_path: Path
    schema_path: Path
    exists: bool
    pending_migrations: tuple[str, ...]
    schema_metadata: dict[str, str]


TARGET_SPECS: dict[str, MigrationTargetSpec] = {
    "notification": MigrationTargetSpec(name="notification", schema_name="sqlite_notification.schema"),
    "metrics": MigrationTargetSpec(name="metrics", schema_name="sqlite_metrics.schema"),
    "client_metrics": MigrationTargetSpec(name="client_metrics", schema_name="sqlite_client_metrics.schema"),
    "price_events": MigrationTargetSpec(name="price_events", schema_name="sqlite_price_events.schema"),
    "webpush": MigrationTargetSpec(name="webpush", schema_name="sqlite_webpush.schema"),
}


def build_bootstrapper(
    *,
    target: str,
    db_path: Path,
    selection_column: str | None = None,
    group_filter_column: str = CANONICAL_GROUP_FILTER_COLUMN,
    legacy_group_filter_columns: Sequence[str] = (),
    legacy_product_filter_columns: Sequence[str] = (),
) -> SQLiteBootstrapper:
    spec = TARGET_SPECS[target]
    args = argparse.Namespace(
        selection_column=selection_column,
        group_filter_column=group_filter_column,
        legacy_group_filter_column=list(legacy_group_filter_columns),
        legacy_product_filter_column=list(legacy_product_filter_columns),
    )
    return SQLiteBootstrapper(
        db_path=db_path,
        schema_path=resolve_schema_path(spec.schema_name),
        locking_mode="NORMAL",
        migrations=spec.build_migrations(args),
    )


def inspect_database(bootstrapper: SQLiteBootstrapper, *, target: str) -> MigrationStatus:
    metadata: dict[str, str] = {}
    if bootstrapper.db_path.exists():
        with platform_sqlite.connect(bootstrapper.db_path, locking_mode="NORMAL") as conn:
            rows = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_metadata'
                """
            ).fetchall()
            if rows:
                metadata = dict(conn.execute("SELECT key, value FROM schema_metadata").fetchall())
    else:
        metadata = {
            "schema_name": bootstrapper.schema_metadata.name,
            "schema_sha256": bootstrapper.schema_metadata.sha256,
            "schema_path": str(bootstrapper.schema_metadata.source_path),
        }

    return MigrationStatus(
        target=target,
        db_path=bootstrapper.db_path,
        schema_path=bootstrapper.schema_metadata.source_path,
        exists=bootstrapper.db_path.exists(),
        pending_migrations=bootstrapper.pending_migrations(),
        schema_metadata=metadata,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="price-platform-migrate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("check", "apply"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("target", choices=sorted(TARGET_SPECS))
        subparser.add_argument("db_path", type=Path)
        subparser.add_argument("--selection-column", default=None)
        subparser.add_argument("--group-filter-column", default=CANONICAL_GROUP_FILTER_COLUMN)
        subparser.add_argument("--legacy-group-filter-column", action="append", default=[])
        subparser.add_argument("--legacy-product-filter-column", action="append", default=[])

    return parser


def _render_status(status: MigrationStatus) -> str:
    schema_hash = status.schema_metadata.get("schema_sha256")
    if schema_hash is None:
        schema_hash = hashlib.sha256(status.schema_path.read_bytes()).hexdigest()
    pending = ", ".join(status.pending_migrations) if status.pending_migrations else "none"
    return (
        f"target={status.target}\n"
        f"db={status.db_path}\n"
        f"schema={status.schema_path.name}\n"
        f"exists={'yes' if status.exists else 'no'}\n"
        f"pending={pending}\n"
        f"schema_sha256={schema_hash}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bootstrapper = build_bootstrapper(
        target=args.target,
        db_path=args.db_path,
        selection_column=args.selection_column,
        group_filter_column=args.group_filter_column,
        legacy_group_filter_columns=args.legacy_group_filter_column,
        legacy_product_filter_columns=args.legacy_product_filter_column,
    )

    if args.command == "apply":
        bootstrapper.ensure_ready()

    status = inspect_database(bootstrapper, target=args.target)
    print(_render_status(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
