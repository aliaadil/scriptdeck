"""Tests for the subprocess runner (v0.2 + v0.8 trigger integration).

Covers the per-trigger params path: when a script is run via a trigger that
carries params, those params must reach the script as environment variables.
"""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from scriptrunner.config import Settings
from scriptrunner.db import initialize_database
from scriptrunner.repository import (
    create_schedule_trigger,
    create_script,
    get_run,
)
from scriptrunner.runner import run_script, wait_for_run


@pytest.fixture
def conn(tmp_db_path):
    c = initialize_database(tmp_db_path)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_db_path, storage_dir) -> Settings:
    return Settings(db_path=tmp_db_path, storage_dir=storage_dir)


def _make_script(conn: sqlite3.Connection, storage_dir: Path, body: str) -> dict[str, object]:
    src = storage_dir / "script.py"
    src.write_text(textwrap.dedent(body), encoding="utf-8")
    return create_script(
        conn,
        name="x",
        language="python",
        source_path=str(src),
        interpreter_path="/usr/bin/env python3",
    )


def test_runner_passes_schedule_params_via_environment(conn, storage_dir, settings) -> None:
    """A schedule trigger with params must surface those params to the script
    via the SCRIPTDECK_PARAM_* env vars (and SCRIPTDECK_PARAMS_JSON)."""
    script = _make_script(
        conn,
        storage_dir,
        """\
        import os, json
        env = os.environ
        params = json.loads(env.get('SCRIPTDECK_PARAMS_JSON', '{}'))
        assert params == {'env': 'prod', 'verbose': '1'}, params
        assert env.get('SCRIPTDECK_PARAM_ENV') == 'prod'
        assert env.get('SCRIPTDECK_PARAM_VERBOSE') == '1'
        print('ok')
        """,
    )
    schedule = create_schedule_trigger(
        conn, int(script["id"]), "cron", "*/5 * * * *",
        params={"env": "prod", "verbose": "1"},
    )
    result = run_script(
        connection=conn,
        storage_dir=storage_dir,
        script_id=int(script["id"]),
        trigger_id=int(schedule["id"]),
    )
    assert result.run["status"] == "success", get_run(conn, result.run["id"])
    final = wait_for_run(connection=conn, run_id=result.run["id"], timeout=5.0)
    assert final and final["status"] == "success"


def test_two_schedules_pass_different_params(conn, storage_dir, settings) -> None:
    """Two schedules on the same script must pass their own params independently."""
    script = _make_script(
        conn,
        storage_dir,
        """\
        import os
        env = os.environ.get('SCRIPTDECK_PARAM_ENV', '')
        # cwd is the script's parent dir, so write there
        with open('scriptdeck_marker_' + env, 'w') as f:
            f.write('fired for ' + env)
        """,
    )
    schedule_a = create_schedule_trigger(
        conn, int(script["id"]), "cron", "*/5 * * * *",
        params={"env": "prod"},
    )
    schedule_b = create_schedule_trigger(
        conn, int(script["id"]), "cron", "*/10 * * * *",
        params={"env": "staging"},
    )

    r1 = run_script(
        connection=conn, storage_dir=storage_dir,
        script_id=int(script["id"]), trigger_id=int(schedule_a["id"]),
    )
    r2 = run_script(
        connection=conn, storage_dir=storage_dir,
        script_id=int(script["id"]), trigger_id=int(schedule_b["id"]),
    )
    assert r1.run["status"] == "success", r1.run
    assert r2.run["status"] == "success", r2.run
    # Script's cwd is its parent dir, so the marker files land there.
    script_parent = Path(script["source_path"]).parent
    assert (script_parent / "scriptdeck_marker_prod").exists()
    assert (script_parent / "scriptdeck_marker_staging").exists()


def test_manual_run_without_trigger_has_empty_params(conn, storage_dir, settings) -> None:
    """An ad-hoc POST /api/scripts/<id>/run (no trigger) must not set the
    SCRIPTDECK_PARAM_* env vars."""
    script = _make_script(
        conn,
        storage_dir,
        """\
        import os
        assert 'SCRIPTDECK_PARAMS_JSON' in os.environ, 'expected SCRIPTDECK_PARAMS_JSON to exist'
        import json
        assert json.loads(os.environ['SCRIPTDECK_PARAMS_JSON']) == {}
        """,
    )
    result = run_script(
        connection=conn,
        storage_dir=storage_dir,
        script_id=int(script["id"]),
    )
    assert result.run["status"] == "success", get_run(conn, result.run["id"])
