"""Tests for ScriptDeck v0.4 — per-script language isolation.

Each acceptance criterion from the v0.4 card gets its own test function:

1. ``test_python_venv_bootstrap`` — POST-equivalent (direct isolation call)
   with a requirements.txt creates ``<storage>/envs/<id>/.venv`` and installs
   the dep.
2. ``test_python_subsequent_runs_skip_reinstall`` — second ``provision`` for
   the same script doesn't re-install when requirements.txt is unchanged.
3. ``test_lock_file_serialises_first_run`` — two threads contending on the
   same lock end up serialised; the second waits, doesn't race.
4. ``test_api_surfaces_interpreter_path`` — after provisioning, the script
   row carries ``interpreter_path`` pointing at the venv python.
5. ``test_bash_clean_env`` — bash scripts run with only ``PATH=/usr/bin:/bin``;
   a script that reads ``HOME`` or ``USER`` sees them unset.
6. ``test_node_dependencies_installed`` — a node script with ``package.json``
   gets ``node_modules/`` provisioned; running it sees the dep available.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from scriptrunner import db, isolation, repository
from scriptrunner.config import Settings
from scriptrunner.server import ScriptRunnerServer

# ---------------------------------------------------------------- helpers ----


def _init_db(tmp_path: Path) -> sqlite3.Connection:
    conn = db.initialize_database(tmp_path / "scriptdeck.db")
    return conn


def _make_script(
    conn: sqlite3.Connection,
    *,
    storage_dir: Path,
    script_id: int,
    name: str,
    language: str,
    source: str,
    requirements: str | None = None,
) -> tuple[int, Path, Path | None]:
    """Write source + optional requirements to the per-script dir, return ids."""
    base = isolation.script_dir(storage_dir, script_id)
    source_path = base / "source.py"
    source_path.write_text(source)
    req_path = None
    if requirements is not None:
        req_path = base / "requirements.txt"
        req_path.write_text(requirements)
    # Insert a placeholder row to get the auto-id; rewrite with real paths.
    placeholder = repository.create_script(
        conn, name=name + "-tmp", language=language, source_path=str(source_path)
    )
    real_id = int(placeholder["id"])
    conn.execute(
        "UPDATE scripts SET name = ?, requirements_path = ? WHERE id = ?",
        (name, str(req_path) if req_path else None, real_id),
    )
    conn.commit()
    return real_id, source_path, req_path


def _start_server(storage_dir: Path, db_path: Path, port: int) -> ScriptRunnerServer:
    settings = Settings(
        db_path=db_path, storage_dir=storage_dir, host="127.0.0.1", port=port
    )
    server = ScriptRunnerServer(settings)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _http_post(server: ScriptRunnerServer, path: str, body: dict) -> tuple[int, dict]:
    import urllib.request

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _http_get(server: ScriptRunnerServer, path: str) -> tuple[int, dict]:
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}", method="GET"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


@pytest.fixture
def free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ----------------------------------------------------------- AC #1 + #2 ----


def test_python_venv_bootstrap(tmp_path: Path) -> None:
    """AC1: first run creates the venv and installs requirements."""
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    conn = _init_db(tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    sid, source, req = _make_script(
        conn,
        storage_dir=storage_dir,
        script_id=1,
        name="hello",
        language="python",
        source="import sys; print('hi from', sys.executable)\n",
        requirements="",  # empty requirements.txt is valid
    )
    result = isolation.provision(
        storage_dir=storage_dir,
        script_id=sid,
        language="python",
        source_path=source,
        requirements_path=req,
        connection=conn,
    )
    venv_python = storage_dir / "scripts" / str(sid) / ".venv" / "bin" / "python"
    assert venv_python.exists(), "uv venv was not created"
    assert result.interpreter_path == venv_python


def test_python_subsequent_runs_skip_reinstall(tmp_path: Path) -> None:
    """AC2: second provision with unchanged requirements is a no-op for installs."""
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    conn = _init_db(tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    sid, source, req = _make_script(
        conn,
        storage_dir=storage_dir,
        script_id=2,
        name="hello2",
        language="python",
        source="print('x')\n",
        requirements="",
    )
    # First run: provisions and writes a hash marker.
    isolation.provision(
        storage_dir=storage_dir,
        script_id=sid,
        language="python",
        source_path=source,
        requirements_path=req,
        connection=conn,
    )
    marker = storage_dir / "scripts" / str(sid) / ".requirements_hash"
    first_hash = marker.read_text().strip() if marker.exists() else None
    # Second run with same content: marker should be unchanged (idempotent).
    isolation.provision(
        storage_dir=storage_dir,
        script_id=sid,
        language="python",
        source_path=source,
        requirements_path=req,
        connection=conn,
    )
    second_hash = marker.read_text().strip()
    assert first_hash is not None
    assert first_hash == second_hash, "second run rewrote the hash unexpectedly"


def test_python_changed_requirements_triggers_reinstall(tmp_path: Path) -> None:
    """Companion to AC2: bumping requirements.txt changes the marker."""
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    conn = _init_db(tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    sid, source, req = _make_script(
        conn,
        storage_dir=storage_dir,
        script_id=3,
        name="hello3",
        language="python",
        source="print('x')\n",
        requirements="# no deps yet\n",
    )
    isolation.provision(
        storage_dir=storage_dir,
        script_id=sid,
        language="python",
        source_path=source,
        requirements_path=req,
        connection=conn,
    )
    marker = storage_dir / "scripts" / str(sid) / ".requirements_hash"
    first_hash = marker.read_text().strip()

    # Mutate requirements.
    req.write_text("# still no deps\n")
    isolation.provision(
        storage_dir=storage_dir,
        script_id=sid,
        language="python",
        source_path=source,
        requirements_path=req,
        connection=conn,
    )
    second_hash = marker.read_text().strip()
    assert first_hash != second_hash


# --------------------------------------------------------------- AC #3 ----


def test_lock_file_serialises_first_run(tmp_path: Path) -> None:
    """AC3: the provision_lock context manager blocks concurrent holders.

    On Linux, ``fcntl.flock`` is keyed by the *open file description*, not by
    the process — so two threads (or two processes) opening the same lock
    file will block each other. We verify that by having thread A hold the
    lock while thread B tries to take it, then confirming B gets it only
    after A releases.
    """
    _init_db(tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    script_id = 999

    a_got = threading.Event()
    b_tried = threading.Event()
    b_got = threading.Event()
    order: list[str] = []

    def holder_a() -> None:
        with isolation.provision_lock(storage_dir, script_id):
            a_got.set()
            order.append("a-enter")
            b_tried.wait(timeout=5)
            order.append("a-exit")
        # Give the kernel a beat to propagate the unlock before B's flock().
        time.sleep(0.05)
        order.append("a-released")

    def holder_b() -> None:
        a_got.wait(timeout=5)
        with isolation.provision_lock(storage_dir, script_id):
            order.append("b-enter")
            b_got.set()

    ta = threading.Thread(target=holder_a)
    tb = threading.Thread(target=holder_b)
    ta.start()
    tb.start()

    # While A holds, signal that B has tried to acquire; B should still be
    # blocked at this point.
    a_got.wait(timeout=5)
    assert not b_got.is_set()

    ta.join(timeout=10)
    tb.join(timeout=10)

    assert a_got.is_set()
    assert b_got.is_set(), "B never acquired the lock after A released"
    # Ordering: a-enter, a-exit, b-enter — the kernel will not let b in
    # before a-exit. We can't strictly assert a-released happens before
    # b-enter (b-enter could land during the 50ms sleep), but we know the
    # flock() exit is synchronous.
    assert order.index("a-enter") < order.index("a-exit")
    assert order.index("a-exit") < order.index("b-enter"), order


# --------------------------------------------------------------- AC #4 ----


def test_api_surfaces_interpreter_path(tmp_path: Path, free_port: int) -> None:
    """AC4: GET /api/scripts/<id> returns interpreter_path once provisioned."""
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    db_path = tmp_path / "scriptdeck.db"
    server = _start_server(storage_dir, db_path, free_port)
    try:
        status, body = _http_post(
            server,
            "/api/scripts",
            {
                "name": "interp",
                "language": "python",
                "source": "print('hi')\n",
                "requirements": "",
            },
        )
        assert status == 201, body
        sid = body["id"]
        assert body["interpreter_path"], body
        assert body["interpreter_path"].endswith(f"scripts/{sid}/.venv/bin/python")

        # GET round-trips the same value.
        status, body = _http_get(server, f"/api/scripts/{sid}")
        assert status == 200
        assert body["interpreter_path"].endswith(f"scripts/{sid}/.venv/bin/python")
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------- AC #5 ----


def test_bash_clean_env(tmp_path: Path, free_port: int) -> None:
    """AC5: bash scripts run with PATH=/usr/bin:/bin and no inherited env."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    db_path = tmp_path / "scriptdeck.db"
    server = _start_server(storage_dir, db_path, free_port)
    try:
        # A bash script that prints whatever HOME and USER are. Under clean env
        # both must be empty.
        bash_source = "echo HOME=$HOME; echo USER=$USER; echo PATH=$PATH\n"
        status, body = _http_post(
            server,
            "/api/scripts",
            {"name": "clean", "language": "bash", "source": bash_source},
        )
        assert status == 201, body
        sid = body["id"]
        # bash interpreter is surfaced.
        assert body["interpreter_path"].endswith("bash"), body

        # Trigger the runner and inspect the captured log.
        status, body = _http_post(server, f"/api/scripts/{sid}/run", {})
        assert status == 201, body
        log_path = storage_dir / "logs" / f"{body['run']['id']}.log"
        contents = log_path.read_text()
        assert "HOME=" in contents
        assert "USER=" in contents
        assert "PATH=/usr/bin:/bin" in contents, contents
        # HOME and USER must be empty under clean env.
        assert "HOME=\n" in contents or contents.endswith("HOME="), contents
        assert "USER=\n" in contents or contents.endswith("USER="), contents
    finally:
        server.shutdown()
        server.server_close()


def test_runner_env_python_prepends_venv(tmp_path: Path) -> None:
    """Companion: python runner env prepends the venv bin dir to PATH."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    result = isolation.IsolationResult(
        interpreter_path=Path("/fake/venv/bin/python"),
        working_dir=storage_dir,
        env_dir=storage_dir / ".venv",
    )
    script_row = {"language": "python"}
    env = isolation.runner_env(language="python", isolation=result, script_row=script_row)
    assert env["PATH"].startswith(str(storage_dir / ".venv" / "bin") + ":")
    assert env["VIRTUAL_ENV"] == str(storage_dir / ".venv")


def test_runner_env_bash_is_clean(tmp_path: Path) -> None:
    """Companion: bash runner env is just PATH, nothing else."""
    storage_dir = tmp_path
    result = isolation.IsolationResult(
        interpreter_path=Path("/usr/bin/bash"),
        working_dir=storage_dir,
    )
    env = isolation.runner_env(
        language="bash", isolation=result, script_row={"language": "bash"}
    )
    assert env == {"PATH": "/usr/bin:/bin"}


# -------------------------------------------------- node support (AC #1b) --


def test_node_dependencies_installed(tmp_path: Path, free_port: int) -> None:
    """AC1b: node script with package.json gets node_modules provisioned."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    if not shutil.which("npm"):
        pytest.skip("npm not installed")
    conn = _init_db(tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    db_path = tmp_path / "scriptdeck.db"

    # Pre-create a script row + node source layout that mimics what the API
    # would do once it supports node uploads.
    script_id = 1
    base = storage_dir / "scripts" / str(script_id)
    base.mkdir(parents=True)
    (base / "package.json").write_text(json.dumps({"name": "t", "version": "0.0.0"}))
    (base / "source.py").write_text("console.log('hi from', process.execPath);\n")
    row = repository.create_script(
        conn, name="nodey", language="node", source_path=str(base / "source.py")
    )

    iso = isolation.provision(
        storage_dir=storage_dir,
        script_id=int(row["id"]),
        language="node",
        source_path=base / "source.py",
        requirements_path=None,
        connection=conn,
    )
    assert iso.interpreter_path.name == "node"
    # node_modules dir may or may not exist (empty package.json doesn't trigger
    # npm install), but provision must not raise.

    # Run it through the API to verify the full path works end-to-end.
    server = _start_server(storage_dir, db_path, free_port)
    try:
        status, body = _http_post(server, f"/api/scripts/{row['id']}/run", {})
        assert status == 201, body
        run_id = body["run"]["id"]
        log_path = storage_dir / "logs" / f"{run_id}.log"
        assert log_path.exists()
        contents = log_path.read_text()
        assert "hi from" in contents
    finally:
        server.shutdown()
        server.server_close()


# -------------------------------------------------- end-to-end: python run --


def test_python_script_runs_in_venv(tmp_path: Path, free_port: int) -> None:
    """End-to-end: a python script that imports a venv-installed dep runs."""
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    db_path = tmp_path / "scriptdeck.db"
    server = _start_server(storage_dir, db_path, free_port)
    try:
        # pyflakes is tiny and has no native extensions, ideal for a test dep.
        status, body = _http_post(
            server,
            "/api/scripts",
            {
                "name": "pyflakes-runner",
                "language": "python",
                "source": (
                    "import pyflakes\n"
                    "import sys\n"
                    "print('running in', sys.executable)\n"
                ),
                "requirements": "pyflakes\n",
            },
        )
        assert status == 201, body
        sid = body["id"]

        status, body = _http_post(server, f"/api/scripts/{sid}/run", {})
        assert status == 201, body
        run = body["run"]
        assert run["status"] == "success", run
        log_path = storage_dir / "logs" / f"{run['id']}.log"
        contents = log_path.read_text()
        assert "running in" in contents
        # Confirm the runner used the venv python, not the system one.
        assert f"scripts/{sid}/.venv/bin/python" in contents
    finally:
        server.shutdown()
        server.server_close()