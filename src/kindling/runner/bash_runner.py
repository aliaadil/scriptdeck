from __future__ import annotations

from pathlib import Path

from kindling.runner.sandbox_view import BindMount, SandboxView


class BashRunner:
    name = "bash"

    def resolve_artifact_path(self) -> str:
        # Bash has no dependency manifest; return an empty placeholder name
        # so callers that probe for an artifact get something stable.
        return ""

    async def detect_deps(self, source: str) -> list[str]:
        # Bash has no package manager we manage; scripts either shell out
        # to installed binaries or rely on builtins.
        return []

    async def provision(self, work_dir: Path, deps: list[str]) -> Path:
        # Bash is interpreter-free from our side: /usr/bin/env is on PATH
        # in the sandboxed chroot and resolves `bash` via the WHITELIST.
        return Path("/usr/bin/env")

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str],
        *, param_argv: list[str] | None = None,
    ) -> list[str]:
        cmd = [str(interpreter), "bash", str(source_path)]
        if param_argv:
            cmd.extend(param_argv)
        return cmd

    def sandbox_view(self) -> SandboxView:
        return SandboxView(binds=[
            BindMount(host=Path("/bin/bash"), jail="/bin/bash"),
            BindMount(host=Path("/usr/bin/env"), jail="/usr/bin/env"),
            BindMount(host=Path("/etc/passwd"), jail="/etc/passwd"),
            BindMount(host=Path("/etc/group"), jail="/etc/group"),
        ])
