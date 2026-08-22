from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from kindling.runner.sandbox_view import BindMount, SandboxView

if TYPE_CHECKING:
    from kindling.services.log_broker import LogBroker


class NodeRunner:
    name = "node"

    def resolve_artifact_path(self) -> str:
        return "package.json"

    async def detect_deps(self, source: str) -> list[str]:
        from kindling.services.dep_detect import detect_node_deps
        return detect_node_deps(source)

    async def provision(
        self,
        work_dir: Path,
        deps: list[str],
        artifact_path: Path | None = None,
        log_broker: LogBroker | None = None,
        run_id: int | None = None,
    ) -> Path:
        pkg_path = work_dir / self.resolve_artifact_path()
        if artifact_path is not None and artifact_path.exists():
            artifact_text = artifact_path.read_text(encoding="utf-8")
            pkg_path.write_text(artifact_text, encoding="utf-8")
            data = json.loads(artifact_text)
            deps_for_log = list((data.get("dependencies") or {}).keys())
        else:
            data = {"name": "kindling-script", "version": "1.0.0", "private": True}
            data["dependencies"] = {d: "*" for d in deps}
            pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            deps_for_log = deps

        if deps_for_log:
            n = len(deps_for_log)
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"▶ Installing {n} packages…\n", 0)
            try:
                await _run(["npm", "install", "--silent"], cwd=work_dir)
            except Exception as exc:
                if log_broker is not None and run_id is not None:
                    await log_broker.publish(run_id, f"✖ Install failed: {exc}\n", 0)
                raise
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"✔ Installed {n} packages\n", 0)
        return Path("node")  # resolved on PATH

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
