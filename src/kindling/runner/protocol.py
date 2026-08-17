from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from kindling.runner.sandbox_view import SandboxView


@runtime_checkable
class LanguageRunner(Protocol):
    name: str

    async def detect_deps(self, source: str) -> list[str]: ...

    def resolve_artifact_path(self) -> str: ...

    async def provision(self, work_dir: Path, deps: list[str]) -> Path: ...

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]: ...

    def sandbox_view(self) -> SandboxView: ...
