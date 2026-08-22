from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kindling.runner.lock import per_script_lock
from kindling.services.log_broker import LogBroker

log = logging.getLogger(__name__)


@dataclass
class Script:
    id: int
    user_id: int
    name: str
    language: str
    source_path: Path
    entrypoint: str
    scripts_dir: Path
    requirements: list[str]


@dataclass
class RunResult:
    exit_code: int
    log_path: Path
    # Space-joined argv as actually handed to the subprocess — captured
    # so the run row records "what command produced these logs". None
    # when the command was never assembled (e.g. the runner failed
    # before interpreter resolution).
    command: str | None = None


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
    # Optional per-trigger params to export as KINDLING_PARAM_<KEY>=<value>.
    # Merged AFTER the user's encrypted .env so the user's values win on
    # conflict (we don't want a low-trust webhook to overwrite a secret).
    param_env: dict[str, str] | None = None,
    # Language-mapped argv appended after the script entrypoint. python/bash
    # get positional args (values only), node gets --key value pairs. None or
    # [] means no extra argv — the runner behaves the same as a no-params
    # call today.
    param_argv: list[str] | None = None,
    active_procs: dict[int, asyncio.subprocess.Process] | None = None,
) -> RunResult:
    from kindling.config import get_settings
    from kindling.runner.registry import get_runner

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
            # Captured once build_command resolves the interpreter +
            # source + param_argv tuple. Stays None if the runner
            # raised before that point — those runs leave the column
            # NULL instead of recording a partial/incorrect command.
            command_str: str | None = None
            try:
                runner = get_runner(script.language)
                if script.language == "python":
                    work_dir = user_root / "venvs" / str(script.id)
                else:
                    work_dir = (user_root / "node_modules" / str(script.id))
                work_dir.mkdir(parents=True, exist_ok=True)
                artifact_filename = runner.resolve_artifact_path()
                script_source_dir = script.source_path.parent
                artifact_candidate = script_source_dir / artifact_filename
                artifact_path = (
                    artifact_candidate if artifact_candidate.exists() else None
                )
                interpreter = await runner.provision(
                    work_dir,
                    script.requirements,
                    artifact_path=artifact_path,
                    log_broker=log_broker,
                    run_id=run_id,
                )

                script_env: dict[str, str] = {}
                if env_ciphertext and env_nonce:
                    decrypted = env_service.decrypt_lines(env_ciphertext, env_nonce)
                    if isinstance(decrypted, dict):
                        script_env = decrypted

                # Apply trigger params FIRST so the user's .env can win on
                # conflict — a low-trust webhook MUST NOT be able to
                # overwrite a secret the script owner set.
                if param_env:
                    script_env = {**param_env, **script_env}

                if settings.sandbox_enabled:
                    # Imports are lazy because the sandbox module dlopens
                    # libc.so.6 at import time, which fails on non-Linux
                    # hosts. The legacy path must remain runnable everywhere.
                    from kindling.runner.sandbox import run_sandboxed
                    from kindling.runner.sandbox_view import scrub_env

                    merged_env = scrub_env(script_env)
                    interpreter_path = (
                        Path("/usr/bin/python3") if script.language == "python"
                        else Path("/usr/bin/node")
                    )
                    source_jail = Path(f"/scripts/{script.id}/{script.source_path.name}")
                    cmd = runner.build_command(
                        interpreter_path, source_jail, merged_env,
                        param_argv=param_argv,
                    )
                    # Record what we're about to invoke so the run row
                    # can answer "which command produced these logs?"
                    # even after the subprocess is gone.
                    command_str = " ".join(str(p) for p in cmd)
                    rv = await run_sandboxed(
                        user_id=script.user_id,
                        script_id=script.id,
                        cmd=cmd,
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
                        cmd = runner.build_command(
                            interpreter, script.source_path, merged_env,
                            param_argv=param_argv,
                        )
                        command_str = " ".join(str(p) for p in cmd)
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            cwd=str(work_dir),
                            env=merged_env,
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
    return RunResult(
        exit_code=exit_code, log_path=log_path, command=command_str,
    )
