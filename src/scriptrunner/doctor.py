"""``scriptdeck doctor`` — operator-facing health check CLI.

Reports a fixed-shape plain-text report that an operator can paste into a
ticket or pipe into health-monitoring scripts. Exit code is 0 when every
check is OK, 1 otherwise.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .db import initialize_database, table_names
from .repository import (
    list_orphaned_runs,
    list_runs,
    list_scripts,
    list_triggers,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str

    def render(self) -> str:
        status = "OK" if self.ok else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def _check_db_writable(settings: Settings) -> CheckResult:
    """The DB path parent must exist and a fresh connection must open."""
    try:
        path = Path(settings.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = initialize_database(settings.db_path)
        try:
            tables = sorted(table_names(conn))
        finally:
            conn.close()
        return CheckResult(
            "db_path_writable",
            True,
            f"{path} (tables: {', '.join(tables) or 'none'})",
        )
    except OSError as exc:
        return CheckResult("db_path_writable", False, f"{settings.db_path}: {exc}")
    except Exception as exc:  # sqlite errors etc.
        return CheckResult("db_path_writable", False, f"{settings.db_path}: {exc}")


def _check_storage_writable(settings: Settings) -> CheckResult:
    try:
        path = Path(settings.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".scriptdeck-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult("storage_dir_writable", True, str(path))
    except OSError as exc:
        return CheckResult("storage_dir_writable", False, f"{settings.storage_dir}: {exc}")


def _check_port_free(settings: Settings) -> CheckResult:
    """Try to bind the configured port. If the bind fails, the port is busy."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((settings.host, settings.port))
        return CheckResult(
            "port_free",
            True,
            f"{settings.host}:{settings.port} is free",
        )
    except OSError as exc:
        return CheckResult(
            "port_free",
            False,
            f"{settings.host}:{settings.port} is in use: {exc}",
        )


def _check_db_connectivity(settings: Settings, *, threshold_seconds: int = 3600) -> CheckResult:
    """Open a connection, count rows in each table, list orphaned runs."""
    try:
        conn = initialize_database(settings.db_path)
    except Exception as exc:
        return CheckResult("db_connectivity", False, str(exc))

    try:
        scripts = list_scripts(conn)
        triggers = list_triggers(conn)
        runs = list_runs(conn)
        orphaned = list_orphaned_runs(conn, _iso_threshold(threshold_seconds))
    except Exception as exc:
        return CheckResult("db_connectivity", False, f"query failed: {exc}")
    finally:
        conn.close()

    return CheckResult(
        "db_connectivity",
        True,
        f"scripts={len(scripts)} triggers={len(triggers)} runs={len(runs)} "
        f"orphaned_runs={len(orphaned)}",
    )


def _iso_threshold(seconds: int) -> str:
    """Return an ISO-8601 timestamp ``seconds`` before *now* (UTC)."""
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _tail_log(log_path: str | None, lines: int = 10) -> list[str]:
    if not log_path:
        return []
    try:
        with open(log_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return [f"<unable to read {log_path}>"]
    text = data.decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    return all_lines[-lines:]


def collect_report(
    settings: Settings,
    *,
    orphaned_threshold_seconds: int = 3600,
    log_tail_lines: int = 10,
) -> dict[str, Any]:
    """Run every check and return a structured report dict."""
    checks = [
        _check_db_writable(settings),
        _check_storage_writable(settings),
        _check_port_free(settings),
        _check_db_connectivity(settings, threshold_seconds=orphaned_threshold_seconds),
    ]

    # Pull the actual rows for the human-readable section.
    conn = initialize_database(settings.db_path)
    try:
        scripts = list_scripts(conn)
        triggers = list_triggers(conn)
        runs = list_runs(conn)
        orphaned = list_orphaned_runs(
            conn, _iso_threshold(orphaned_threshold_seconds)
        )
    finally:
        conn.close()

    latest_run = runs[-1] if runs else None
    latest_log_tail: list[str] = []
    if latest_run is not None:
        latest_log_tail = _tail_log(latest_run.get("log_path"), log_tail_lines)

    return {
        "settings": {
            "db_path": str(settings.db_path),
            "storage_dir": str(settings.storage_dir),
            "host": settings.host,
            "port": settings.port,
        },
        "checks": [
            {"name": c.name, "ok": c.ok, "message": c.message} for c in checks
        ],
        "all_ok": all(c.ok for c in checks),
        "counts": {
            "scripts": len(scripts),
            "triggers": len(triggers),
            "runs": len(runs),
            "orphaned_runs": len(orphaned),
        },
        "orphaned_runs": [
            {
                "id": r["id"],
                "script_id": r["script_id"],
                "trigger_id": r["trigger_id"],
                "started_at": r["started_at"],
            }
            for r in orphaned
        ],
        "latest_run": (
            {
                "id": latest_run["id"],
                "script_id": latest_run["script_id"],
                "trigger_id": latest_run["trigger_id"],
                "status": latest_run["status"],
                "started_at": latest_run["started_at"],
                "ended_at": latest_run["ended_at"],
                "log_path": latest_run.get("log_path"),
                "log_tail": latest_log_tail,
            }
            if latest_run is not None
            else None
        ),
    }


def render_report(report: dict[str, Any]) -> str:
    """Render a structured report dict as a fixed-shape plain-text report."""
    lines: list[str] = []
    settings = report["settings"]
    lines.append("ScriptDeck doctor")
    lines.append("=================")
    lines.append(
        f"db_path     : {settings['db_path']}\n"
        f"storage_dir : {settings['storage_dir']}\n"
        f"host:port   : {settings['host']}:{settings['port']}"
    )
    lines.append("")
    lines.append("Checks")
    lines.append("------")
    for check in report["checks"]:
        status = "OK  " if check["ok"] else "FAIL"
        lines.append(f"[{status}] {check['name']}: {check['message']}")
    lines.append("")
    counts = report["counts"]
    lines.append(
        "Counts\n"
        "------\n"
        f"scripts        : {counts['scripts']}\n"
        f"triggers       : {counts['triggers']}\n"
        f"runs           : {counts['runs']}\n"
        f"orphaned_runs  : {counts['orphaned_runs']}"
    )
    lines.append("")
    lines.append("Orphaned runs (started > 1h ago, never ended)")
    lines.append("---------------------------------------------")
    if not report["orphaned_runs"]:
        lines.append("(none)")
    else:
        for row in report["orphaned_runs"]:
            lines.append(
                f"run_id={row['id']} script_id={row['script_id']} "
                f"trigger_id={row['trigger_id']} started_at={row['started_at']}"
            )
    lines.append("")
    lines.append("Latest run")
    lines.append("----------")
    latest = report["latest_run"]
    if latest is None:
        lines.append("(no runs yet)")
    else:
        lines.append(
            f"run_id={latest['id']} script_id={latest['script_id']} "
            f"trigger_id={latest['trigger_id']} status={latest['status']}"
        )
        lines.append(f"started_at={latest['started_at']} ended_at={latest['ended_at']}")
        lines.append(f"log_path={latest['log_path']}")
        lines.append("log tail (last 10 lines):")
        if latest["log_tail"]:
            lines.extend(latest["log_tail"])
        else:
            lines.append("(no log content)")
    lines.append("")
    return "\n".join(lines)


def run_doctor(settings: Settings | None = None) -> int:
    """Run the doctor and print the report. Returns a process exit code."""
    settings = settings or Settings.from_env()
    report = collect_report(settings)
    print(render_report(report))
    return 0 if report["all_ok"] else 1


def main() -> None:
    import sys

    sys.exit(run_doctor())
