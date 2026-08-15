from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scriptdeck.runner.lock import per_script_lock
from scriptdeck.runner.registry import get_runner
from scriptdeck.services.log_broker import LogBroker

log = logging.getLogger(__name__)


@dataclass
class Script:
    id: int
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
    logs_dir = storage_dir / "logs"
    scripts_dir = storage_dir / "scripts"
    venvs_dir = storage_dir / "venvs"
    node_modules_dir = storage_dir / "node_modules"
    locks_dir = storage_dir / "locks"
    logs_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    venvs_dir.mkdir(parents=True, exist_ok=True)
    node_modules_dir.mkdir(parents=True, exist_ok=True)
    locks_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / f"{run_id}.log"
    script_work = scripts_dir / str(script.id)
    script_work.mkdir(parents=True, exist_ok=True)
    if script.language == "python":
        work_dir = venvs_dir / str(script.id)
    else:
        work_dir = node_modules_dir / str(script.id)
    work_dir.mkdir(parents=True, exist_ok=True)

    async with concurrency:
        async with per_script_lock(script.id, locks_dir):
            exit_code: int = -1
            status: str = "error"
            log_fh = None
            try:
                runner = get_runner(script.language)
                interpreter = await runner.provision(work_dir, script.requirements)
                merged_env: dict[str, str] = dict(os.environ)
                # Decrypt per-script env if present. Failures propagate so the
                # caller can mark the run as error rather than silently running
                # without the script's env.
                if env_ciphertext and env_nonce:
                    env_lines = env_service.decrypt_lines(env_ciphertext, env_nonce)
                    if isinstance(env_lines, dict):
                        merged_env.update(env_lines)

                log_fh = log_path.open("wb")
                offset = 0
                proc = await asyncio.create_subprocess_exec(
                    *runner.build_command(interpreter, script.source_path, merged_env),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(work_dir),
                )
                if active_procs is not None:
                    active_procs[run_id] = proc
                assert proc.stdout is not None
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
                status = "success" if exit_code == 0 else "failure"
            except Exception as exc:
                log.exception("run_script failed for run_id=%s: %s", run_id, exc)
                exit_code = -1
                status = "error"
            finally:
                if active_procs is not None:
                    active_procs.pop(run_id, None)
                if log_fh is not None:
                    log_fh.close()
                await log_broker.close(run_id, status=status, exit_code=exit_code)
    return RunResult(exit_code=exit_code, log_path=log_path)
