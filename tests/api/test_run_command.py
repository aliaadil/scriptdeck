"""Migration 018: every run row records the command that was handed to
the subprocess, so the UI can show "what command produced these logs?"
without re-resolving trigger params by hand.
"""
from __future__ import annotations

import asyncio
import base64
import os
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import runs, scripts, users


@pytest.fixture
async def cmd_ctx(tmp_path):
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    (storage / "logs").mkdir(parents=True)
    # The runner needs an actual source file on disk; otherwise
    # create_subprocess_exec raises FileNotFoundError before command_str
    # is consumed and the run row stays command=NULL.
    scripts_dir = storage / "scripts" / "10"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "hello.py").write_text(
        "import sys\nprint('ok', *sys.argv[1:])\n", encoding="utf-8"
    )
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="hello", language="python",
            source_path="scripts/10/hello.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_manual_run_records_executed_command(cmd_ctx, monkeypatch_auth):
    """After a manual run with params_argv the runs.command column holds
    the space-joined argv the runner handed to subprocess — interpreter
    + source path + the param tokens, in that order."""
    ac, app = cmd_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)

    r = await ac.post(
        "/api/kindling/scripts/10/run",
        json={"params_argv": ["hello", "world"]},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    # The runner runs as a background task — wait for it to land its
    # terminal status so we don't race the UPDATE.
    for _ in range(50):
        async with app.state.session_factory() as s:
            row = (
                await s.execute(
                    select(runs.c.status, runs.c.command).where(runs.c.id == run_id)
                )
            ).one()
        if row[0] in ("success", "failure", "error"):
            break
        await asyncio.sleep(0.05)

    cmd = row[1]
    assert cmd is not None, "command should be persisted"
    assert cmd.endswith("hello.py hello world"), (
        f"expected trailing 'hello.py hello world', got {cmd!r}"
    )
    tokens = cmd.split(" ")
    assert tokens[0]  # interpreter (resolved to absolute path on real runs)
    # Last three tokens are: <full script path> <param1> <param2>
    assert tokens[-1] == "world"
    assert tokens[-2] == "hello"
    assert tokens[-3].endswith("hello.py")
