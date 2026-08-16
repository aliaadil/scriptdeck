from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scriptdeck.runner.lock import per_script_lock
from scriptdeck.services.log_broker import LogBroker

log = logging.getLogger(__name__)


@dataclass
class Script:
    id: int
    user_id: int
    name: str
    language: str
    source_path: Path
    requirements: list[str]


@dataclass
class RunResult:
    exit_code: int
    log_path: Path


class EnvLike(Protocol):
    def decrypt_lines(self, *args, **kwargs) -> dict[str, str]: ...


async def run_script(
    *,
    run_id: int,
    script: Script,
    env_service: EnvLike,
    log_broker: LogBroker,
    concurrency: asyncio.Semaphore,
    storage_dir: Path,
    env_ciphertext: str | None = None,
    env_nonce: str | None = None,
    active_procs: dict[int, asyncio.subprocess.Process] | None = None,
) -> RunResult:
    from scriptdeck.config import get_settings
    from scriptdeck.runner.registry import get_runner

    settings = get_settings()
    logs_dir = storage_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{run_id}.log"

    user_root = (storage_dir / "users" / str(script.user_id)).resolve()
    user_root.mkdir(parents=True, exist_ok=True)

    async with concurrency:
        async with per_script_lock(script.id, storage_dir / "locks"):
            exit_code: int = -1
            status: str = "error"
            try:
                runner = get_runner(script.language)
                if script.language == "python":
                    work_dir = user_root / "venvs" / str(script.id)
                else:
                    work_dir = (user_root / "node_modules" / str(script.id))
                work_dir.mkdir(parents=True, exist_ok=True)
                interpreter = await runner.provision(work_dir, script.requirements)

                script_env: dict[str, str] = {}
                if env_ciphertext and env_nonce:
                    decrypted = env_service.decrypt_lines(env_ciphertext, env_nonce)
                    if isinstance(decrypted, dict):
                        script_env = decrypted

                if settings.sandbox_enabled:
                    # Imports are lazy because the sandbox module dlopens
                    # libc.so.6 at import time, which fails on non-Linux
                    # hosts. The legacy path must remain runnable everywhere.
                    from scriptdeck.runner.sandbox import run_sandboxed
                    from scriptdeck.runner.sandbox_view import scrub_env

                    merged_env = scrub_env(script_env)
                    interpreter_path = (
                        Path("/usr/bin/python3") if script.language == "python"
                        else Path("/usr/bin/node")
                    )
                    source_jail = Path(f"/scripts/{script.id}/{script.source_path.name}")
                    rv = await run_sandboxed(
                        user_id=script.user_id,
                        script_id=script.id,
                        cmd=runner.build_command(interpreter_path, source_jail, merged_env),
                        env=merged_env,
                        user_root=user_root,
                        view=runner.sandbox_view(),
                        run_id=run_id,
                        log_path=log_path,
                    )
                    exit_code = rv
                else:
                    merged_env = dict(os.environ)
                    merged_env.update(script_env)
                    log_fh = log_path.open("wb")
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            *runner.build_command(interpreter, script.source_path, merged_env),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            cwd=str(work_dir),
                        )
                        if active_procs is not None:
                            active_procs[run_id] = proc
                        assert proc.stdout is not None
                        offset = 0
                        while True:
                            chunk = await proc.stdout.readline()
                            if not chunk:
                                break
                            log_fh.write(chunk)
                            log_fh.flush()
                            await log_broker.publish(
                                run_id, chunk.decode("utf-8", errors="replace"), offset
                            )
                            offset += len(chunk)
                        exit_code = await proc.wait()
                    finally:
                        if active_procs is not None:
                            active_procs.pop(run_id, None)
                        log_fh.close()

                status = "success" if exit_code == 0 else "failure"
            except Exception as exc:
                log.exception("run_script failed for run_id=%s: %s", run_id, exc)
                exit_code = -1
                status = "error"
            await log_broker.close(run_id, status=status, exit_code=exit_code)
    return RunResult(exit_code=exit_code, log_path=log_path)
