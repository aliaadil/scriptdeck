from __future__ import annotations

import asyncio
from pathlib import Path

from scriptdeck.runner.sandbox_view import BindMount, SandboxView


class PythonRunner:
    name = "python"

    def resolve_artifact_path(self) -> str:
        return "requirements.txt"

    async def detect_deps(self, source: str) -> list[str]:
        from scriptdeck.services.dep_detect import detect_python_deps
        return detect_python_deps(source)

    async def provision(self, work_dir: Path, deps: list[str]) -> Path:
        req = work_dir / self.resolve_artifact_path()
        req.write_text("\n".join(deps) + ("\n" if deps else ""), encoding="utf-8")
        venv = work_dir / ".venv"
        if not (venv / "bin" / "python").exists():
            await _run(["uv", "venv", str(venv)])
        if deps:
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
        return (venv / "bin" / "python").resolve()

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]:
        return [str(interpreter), str(source_path)]

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
