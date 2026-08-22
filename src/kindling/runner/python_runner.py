from __future__ import annotations

import asyncio
from pathlib import Path

from kindling.runner.sandbox_view import BindMount, SandboxView


class PythonRunner:
    name = "python"

    def resolve_artifact_path(self) -> str:
        return "requirements.txt"

    async def detect_deps(self, source: str) -> list[str]:
        from kindling.services.dep_detect import detect_python_deps
        return detect_python_deps(source)

    async def provision(
        self,
        work_dir: Path,
        deps: list[str],
        artifact_path: Path | None = None,
        log_broker: "LogBroker | None" = None,
        run_id: int | None = None,
    ) -> Path:
        req = work_dir / self.resolve_artifact_path()
        if artifact_path is not None and artifact_path.exists():
            # Honor the user-edited artifact verbatim; preserve pin versions.
            artifact_text = artifact_path.read_text(encoding="utf-8")
            req.write_text(artifact_text, encoding="utf-8")
            deps_for_log = [
                line.strip()
                for line in artifact_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            req.write_text("\n".join(deps) + ("\n" if deps else ""), encoding="utf-8")
            deps_for_log = deps

        venv = work_dir / ".venv"
        if not (venv / "bin" / "python").exists():
            await _run(["uv", "venv", str(venv)])
        if deps_for_log:
            n = len(deps_for_log)
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"▶ Installing {n} packages…\n", 0)
            try:
                await _run(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str((venv / "bin" / "python").resolve()),
                        "-r",
                        str(req.resolve()),
                    ]
                )
            except Exception as exc:
                if log_broker is not None and run_id is not None:
                    await log_broker.publish(run_id, f"✖ Install failed: {exc}\n", 0)
                raise
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"✔ Installed {n} packages\n", 0)
        return (venv / "bin" / "python").resolve()

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str],
        *, param_argv: list[str] | None = None,
    ) -> list[str]:
        cmd = [str(interpreter), str(source_path)]
        if param_argv:
            cmd.extend(param_argv)
        return cmd

    def sandbox_view(self) -> SandboxView:
        return SandboxView(binds=[
            BindMount(host=Path("/usr/bin/python3"), jail="/usr/bin/python3"),
            BindMount(host=Path("/usr/lib/python3.12"), jail="/usr/lib/python3.12"),
            BindMount(host=Path("/usr/local/lib/python3.12"), jail="/usr/local/lib/python3.12"),
            BindMount(host=Path("/etc/ssl"), jail="/etc/ssl"),
            BindMount(host=Path("/etc/passwd"), jail="/etc/passwd"),
            BindMount(host=Path("/etc/group"), jail="/etc/group"),
        ])


async def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {cmd}\n{out.decode()}\n{err.decode()}"
        )
