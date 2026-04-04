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


def test_migration_cli_applies_price_event_legacy_fixture(tmp_path: pathlib.Path, capsys) -> None:
    db_path = tmp_path / "price_events.db"
    fixture = pathlib.Path("tests/fixtures/legacy_db/price_events_color_key.sql")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_load_fixture(fixture))

    exit_code = migration_cli.main(
        ["apply", "price_events", str(db_path), "--selection-column", "color_key"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pending=none" in captured.out
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(price_events)").fetchall()}
    assert "selection_key" in columns
    assert "color_key" not in columns


def test_migration_cli_applies_webpush_legacy_fixture(tmp_path: pathlib.Path, capsys) -> None:
    db_path = tmp_path / "webpush.db"
    fixture = pathlib.Path("tests/fixtures/legacy_db/webpush_maker_filter.sql")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_load_fixture(fixture))

    exit_code = migration_cli.main(
        [
            "apply",
            "webpush",
            str(db_path),
            "--group-filter-column",
            "maker_filter",
            "--legacy-product-filter-column",
            "item_filter",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pending=none" in captured.out
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(webpush_subscriptions)").fetchall()}
    assert "group_filter" in columns
    assert "product_filter" in columns


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
