from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scriptdeck.runner.sandbox_view import BindMount, SandboxView


class NodeRunner:
    name = "node"

    def resolve_artifact_path(self) -> str:
        return "package.json"

    async def detect_deps(self, source: str) -> list[str]:
        from scriptdeck.services.dep_detect import detect_node_deps
        return detect_node_deps(source)

    async def provision(self, work_dir: Path, deps: list[str]) -> Path:
        pkg_path = work_dir / self.resolve_artifact_path()
        if pkg_path.exists():
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        else:
            data = {"name": "scriptdeck-script", "version": "1.0.0", "private": True}
        data["dependencies"] = {d: "*" for d in deps}
        pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if deps:
            await _run(["npm", "install", "--silent"], cwd=work_dir)
        return Path("node")  # resolved on PATH

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]:
        return [str(interpreter), str(source_path)]

    def sandbox_view(self) -> SandboxView:
        return SandboxView(binds=[
            BindMount(host=Path("/usr/bin/node"), jail="/usr/bin/node"),
            BindMount(host=Path("/usr/lib/x86_64-linux-gnu"), jail="/usr/lib/x86_64-linux-gnu"),
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
