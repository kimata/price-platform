from __future__ import annotations

import pathlib
import sqlite3

from price_platform import migration_cli


def _load_fixture(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_migration_cli_check_reports_pending_for_missing_db(tmp_path: pathlib.Path, capsys) -> None:
    db_path = tmp_path / "metrics.db"

    exit_code = migration_cli.main(["check", "metrics", str(db_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "exists=no" in captured.out
    assert "pending=none" in captured.out


def test_migration_cli_applies_client_metrics_legacy_fixture(tmp_path: pathlib.Path, capsys) -> None:
    db_path = tmp_path / "client_metrics.db"
    fixture = pathlib.Path("tests/fixtures/legacy_db/client_metrics_without_social.sql")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_load_fixture(fixture))

    exit_code = migration_cli.main(["apply", "client_metrics", str(db_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pending=none" in captured.out
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    assert "social_referral_events" in tables
