"""Tests for the `scriptdeck doctor` CLI."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scriptrunner.config import Settings
from scriptrunner.db import initialize_database
from scriptrunner.doctor import (
    CheckResult,
    collect_report,
    render_report,
    run_doctor,
)
from scriptrunner.repository import create_run, create_script


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    db = tmp_path / "scriptdeck.db"
    storage = tmp_path / "storage"
    return Settings(db_path=db, storage_dir=storage, host="127.0.0.1", port=0)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_check_result_rendering() -> None:
    ok = CheckResult(name="x", ok=True, message="fine")
    fail = CheckResult(name="y", ok=False, message="bad")
    assert ok.render() == "[OK] x: fine"
    assert fail.render() == "[FAIL] y: bad"


def test_collect_report_on_empty_db(settings: Settings) -> None:
    report = collect_report(settings)
    assert report["all_ok"] is True
    assert report["counts"] == {
        "scripts": 0, "triggers": 0, "runs": 0, "orphaned_runs": 0,
    }
    assert report["orphaned_runs"] == []
    assert report["latest_run"] is None
    assert report["settings"]["db_path"] == str(settings.db_path)


def test_collect_report_detects_orphaned_runs(settings: Settings) -> None:
    conn = initialize_database(settings.db_path)
    try:
        script = create_script(conn, name="x", language="python", source_path="/x.py")
        long_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        create_run(
            conn,
            script_id=script["id"],
            trigger_id=None,
            started_at=long_ago,
            status="error",
        )
    finally:
        conn.close()

    report = collect_report(settings)
    assert report["counts"]["orphaned_runs"] == 1
    assert len(report["orphaned_runs"]) == 1
    assert report["orphaned_runs"][0]["script_id"] == script["id"]


def test_collect_report_port_busy_marks_failure(tmp_path: Path) -> None:
    busy_port = _find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", busy_port))
        sock.listen(1)
        try:
            settings = Settings(
                db_path=tmp_path / "scriptdeck.db",
                storage_dir=tmp_path / "storage",
                host="127.0.0.1",
                port=busy_port,
            )
            report = collect_report(settings)
            port_check = next(c for c in report["checks"] if c["name"] == "port_free")
            assert port_check["ok"] is False
            assert report["all_ok"] is False
        finally:
            sock.close()


def test_storage_unwritable_marks_failure(tmp_path: Path) -> None:
    ro_parent = tmp_path / "ro_parent"
    ro_parent.mkdir()
    try:
        os.chmod(ro_parent, 0o500)
        if not os.access(ro_parent, os.W_OK):
            restricted = Settings(
                db_path=tmp_path / "scriptdeck.db",
                storage_dir=ro_parent / "nope",
                host="127.0.0.1",
                port=0,
            )
            report = collect_report(restricted)
            storage_check = next(c for c in report["checks"] if c["name"] == "storage_dir_writable")
            assert storage_check["ok"] is False
        else:
            pytest.skip("unwritable check skipped: chmod ineffective in this environment")
    finally:
        os.chmod(ro_parent, 0o700)


def test_render_report_shape_includes_latest_run_log_tail(tmp_path: Path) -> None:
    db = tmp_path / "scriptdeck.db"
    storage = tmp_path / "storage"
    (storage / "logs").mkdir(parents=True, exist_ok=True)
    log = storage / "logs" / "1.log"
    log.write_text("line1\nline2\nline3\n", encoding="utf-8")

    settings = Settings(db_path=db, storage_dir=storage, host="127.0.0.1", port=0)
    conn = initialize_database(db)
    try:
        script = create_script(conn, name="x", language="python", source_path="/x.py")
        create_run(
            conn,
            script_id=script["id"],
            trigger_id=None,
            status="success",
            log_path=str(log),
            log_size_bytes=18,
        )
    finally:
        conn.close()

    report = collect_report(settings)
    text = render_report(report)
    assert "ScriptDeck doctor" in text
    assert "Latest run" in text
    assert "line3" in text


def test_run_doctor_returns_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        db_path=tmp_path / "scriptdeck.db",
        storage_dir=tmp_path / "storage",
        host="127.0.0.1",
        port=0,
    )
    assert run_doctor(settings) == 0
    out = capsys.readouterr().out
    assert "ScriptDeck doctor" in out
