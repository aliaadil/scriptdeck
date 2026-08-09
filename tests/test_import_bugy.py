from __future__ import annotations

import json
from pathlib import Path

from scriptrunner.db import connect
from scriptrunner.importer import import_bugy


def test_imports_scripts_and_schedules_without_execution(tmp_path: Path) -> None:
    source = tmp_path / "bugy"
    source.mkdir()
    marker = tmp_path / "executed"
    (source / "hello.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    (source / "scripts.json").write_text(json.dumps([
        {"id": 10, "name": "hello", "language": "python", "path": "hello.py"},
        {"id": 11, "name": "unsupported", "language": "ruby", "source": "puts 'no'"},
    ]))
    (source / "schedules.json").write_text(json.dumps([
        {"script_id": 10, "cron": "*/5 * * * *", "enabled": True},
        {"script_id": 999, "interval": 60},
    ]))
    db_path = tmp_path / "scriptdeck.db"

    result = import_bugy(source, db_path, tmp_path / "storage")

    assert result == {"scripts": 1, "schedules": 1, "skipped": 2}
    assert not marker.exists()
    connection = connect(db_path)
    script_row = connection.execute("SELECT name, language FROM scripts").fetchone()
    schedule_row = connection.execute("SELECT kind, expression FROM schedules").fetchone()
    assert (script_row["name"], script_row["language"]) == ("hello", "python")
    assert (schedule_row["kind"], schedule_row["expression"]) == ("cron", "*/5 * * * *")


def test_requires_both_export_files(tmp_path: Path) -> None:
    (tmp_path / "scripts.json").write_text("[]")
    try:
        import_bugy(tmp_path, tmp_path / "db.sqlite", tmp_path / "storage")
    except ValueError as exc:
        assert "scripts.json and schedules.json" in str(exc)
    else:
        raise AssertionError("expected ValueError")
