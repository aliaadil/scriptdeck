from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class GcResult:
    deleted: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _log_dirs(storage_dir: Path) -> list[Path]:
    """Collect every directory that may hold .log files, tolerating missing layouts."""
    roots = [storage_dir / "logs"]  # legacy layout
    users_dir = storage_dir / "users"
    try:
        user_dirs = sorted(p for p in users_dir.iterdir() if p.is_dir())
    except OSError:
        # No users/ dir yet (fresh install) or it is unreadable: legacy only.
        user_dirs = []
    roots.extend(p / "logs" for p in user_dirs)
    return [root for root in roots if root.is_dir()]


def gc_logs(*, storage_dir: Path, retention_days: int) -> GcResult:
    """Delete .log files older than retention_days. Idempotent.

    Walks `storage_dir/users/<uid>/logs/*.log` (per-user layout) and
    `storage_dir/logs/*.log` (legacy layout). Run rows are not touched.
    """
    result = GcResult()
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    for root in _log_dirs(storage_dir):
        for log_file in root.glob("*.log"):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime, UTC)
                if mtime < cutoff:
                    log_file.unlink()
                    result.deleted += 1
            except OSError as exc:
                log.warning("retention: failed to gc %s: %s", log_file, exc)
                result.errors.append((str(log_file), str(exc)))
    return result
