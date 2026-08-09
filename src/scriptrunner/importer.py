"""Read-only importer for bugy/script-server JSON exports."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from . import repository
from .db import initialize_database

LOG = logging.getLogger(__name__)
LANGUAGES = {"python": ".py", "javascript": ".js", "node": ".js", "bash": ".sh", "shell": ".sh"}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("scripts") or payload.get("schedules") or payload.get("data")
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must contain a JSON array")
    return [row for row in payload if isinstance(row, dict)]


def import_bugy(source_dir: Path, db_path: Path, storage_dir: Path) -> dict[str, int]:
    """Import script and schedule records without executing imported code."""
    scripts_file = source_dir / "scripts.json"
    schedules_file = source_dir / "schedules.json"
    if not scripts_file.is_file() or not schedules_file.is_file():
        raise ValueError("source directory must contain scripts.json and schedules.json")

    connection = initialize_database(db_path)
    destination = storage_dir / "scripts"
    destination.mkdir(parents=True, exist_ok=True)
    id_map: dict[str, int] = {}
    result = {"scripts": 0, "schedules": 0, "skipped": 0}

    for index, row in enumerate(_load_rows(scripts_file), start=1):
        try:
            old_id = str(row.get("id", index))
            name = str(row.get("name") or row.get("title") or "").strip()
            raw_language = str(row.get("language") or row.get("type") or "").lower()
            language = "javascript" if raw_language == "node" else "bash" if raw_language == "shell" else raw_language
            if not name or language not in LANGUAGES:
                raise ValueError("missing name or unsupported language")
            source_value = row.get("source") or row.get("script") or row.get("path") or row.get("file")
            if not source_value:
                raise ValueError("missing source/script/path")
            candidate = Path(str(source_value))
            source_path = candidate if candidate.is_absolute() else source_dir / candidate
            target = destination / f"imported-{index}{LANGUAGES[raw_language]}"
            if source_path.is_file():
                shutil.copyfile(source_path, target)
            else:
                target.write_text(str(source_value), encoding="utf-8")
            script = repository.create_script(connection, name, language, str(target))
            id_map[old_id] = int(script["id"])
            result["scripts"] += 1
        except (OSError, TypeError, ValueError) as exc:
            LOG.warning("Skipping script row %s: %s", index, exc)
            result["skipped"] += 1

    for index, row in enumerate(_load_rows(schedules_file), start=1):
        try:
            script_id = id_map[str(row.get("script_id") or row.get("scriptId"))]
            cron = row.get("cron") or row.get("cron_expression")
            interval = row.get("interval") or row.get("interval_seconds")
            kind = str(row.get("kind") or ("cron" if cron else "interval" if interval else ""))
            expression = str(row.get("expression") or cron or interval or "")
            repository.create_schedule(
                connection,
                script_id,
                kind,
                expression,
                enabled=bool(row.get("enabled", True)),
            )
            result["schedules"] += 1
        except (KeyError, TypeError, ValueError) as exc:
            LOG.warning("Skipping schedule row %s: %s", index, exc)
            result["skipped"] += 1

    connection.close()
    return result
