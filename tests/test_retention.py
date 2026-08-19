from __future__ import annotations

import os
import time
from pathlib import Path

from kindling.services.retention import GcResult, gc_logs


def test_deletes_old_logs_leaves_recent(tmp_path: Path):
    user1 = tmp_path / "users" / "1" / "logs"
    user1.mkdir(parents=True)
    old = user1 / "old.log"
    new = user1 / "new.log"
    old.write_text("ancient")
    new.write_text("recent")

    # Make "old" 10 days old, "new" 1 day old.
    ten_days_ago = time.time() - 10 * 86400
    one_day_ago = time.time() - 1 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    os.utime(new, (one_day_ago, one_day_ago))

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert isinstance(result, GcResult)
    assert result.deleted == 1
    assert result.errors == []
    assert not old.exists()
    assert new.exists()


def test_idempotent(tmp_path: Path):
    (tmp_path / "users" / "1" / "logs").mkdir(parents=True)
    old = tmp_path / "users" / "1" / "logs" / "old.log"
    old.write_text("x")
    fourteen_days_ago = time.time() - 14 * 86400
    os.utime(old, (fourteen_days_ago, fourteen_days_ago))

    first = gc_logs(storage_dir=tmp_path, retention_days=7)
    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert first.deleted == 1
    assert result.deleted == 0
    assert result.errors == []


def test_handles_missing_user_dir(tmp_path: Path):
    # No users/ dir at all.
    result = gc_logs(storage_dir=tmp_path, retention_days=7)
    assert result.deleted == 0
    assert result.errors == []


def test_legacy_log_dir_also_cleaned(tmp_path: Path):
    legacy = tmp_path / "logs"
    legacy.mkdir()
    old = legacy / "old.log"
    old.write_text("x")
    fourteen_days_ago = time.time() - 14 * 86400
    os.utime(old, (fourteen_days_ago, fourteen_days_ago))

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert result.deleted == 1
    assert result.errors == []


def test_both_layouts_in_one_call(tmp_path: Path):
    legacy = tmp_path / "logs"
    legacy.mkdir()
    user2 = tmp_path / "users" / "2" / "logs"
    user2.mkdir(parents=True)
    stale = time.time() - 14 * 86400

    for path in (legacy / "old.log", user2 / "old.log"):
        path.write_text("x")
        os.utime(path, (stale, stale))
    keep = user2 / "keep.log"
    keep.write_text("x")

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert result.deleted == 2
    assert result.errors == []
    assert keep.exists()


def test_unlink_failure_is_recorded_and_gc_continues(tmp_path: Path, monkeypatch):
    user1 = tmp_path / "users" / "1" / "logs"
    user1.mkdir(parents=True)
    stale = time.time() - 14 * 86400
    doomed = user1 / "a-broken.log"
    fine = user1 / "b-ok.log"
    for path in (doomed, fine):
        path.write_text("x")
        os.utime(path, (stale, stale))

    real_unlink = Path.unlink

    def flaky_unlink(self: Path, *args, **kwargs):
        if self.name == "a-broken.log":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    # The failure is reported, and the other expired file is still collected.
    assert result.deleted == 1
    assert len(result.errors) == 1
    failed_path, message = result.errors[0]
    assert failed_path == str(doomed)
    assert "Permission denied" in message
    assert not fine.exists()


def test_ignores_non_log_files(tmp_path: Path):
    user1 = tmp_path / "users" / "1" / "logs"
    user1.mkdir(parents=True)
    other = user1 / "old.txt"
    other.write_text("x")
    stale = time.time() - 14 * 86400
    os.utime(other, (stale, stale))

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert result.deleted == 0
    assert other.exists()
