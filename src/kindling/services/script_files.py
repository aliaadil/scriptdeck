from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 1_000_000  # 1 MB
PATH_RE = re.compile(r"^[a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*$")


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    updated_at: str


def validate_path(path: str) -> str:
    if not path:
        raise ValueError("path required")
    if "\0" in path:
        raise ValueError("path contains NUL")
    if path.startswith("/") or path.startswith("\\"):
        raise ValueError("absolute path not allowed")
    if ".." in path.split("/"):
        raise ValueError("path traversal not allowed")
    if not PATH_RE.match(path):
        raise ValueError(f"invalid path: {path!r}")
    return path


def _resolve(script_dir: Path, path: str) -> Path:
    validated = validate_path(path)
    target = (script_dir / validated).resolve()
    # Ensure target is inside script_dir
    if not str(target).startswith(str(script_dir.resolve())):
        raise ValueError("path escapes script directory")
    return target


def list_files(script_dir: Path, *, entrypoint: str) -> list[FileEntry]:
    if not script_dir.exists():
        return []
    entries: list[FileEntry] = []
    for p in sorted(script_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(script_dir).as_posix()
        try:
            validate_path(rel)
        except ValueError:
            continue
        stat = p.stat()
        entries.append(FileEntry(path=rel, size=stat.st_size, updated_at=stat.st_mtime.__str__()))
    # Entrypoint first
    entries.sort(key=lambda e: (e.path != entrypoint, e.path))
    return entries


def read_file(script_dir: Path, path: str) -> str:
    target = _resolve(script_dir, path)
    if not target.exists():
        raise FileNotFoundError(path)
    return target.read_text(encoding="utf-8")


def write_file(script_dir: Path, path: str, content: str) -> FileEntry:
    target = _resolve(script_dir, path)
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    stat = target.stat()
    return FileEntry(path=path, size=stat.st_size, updated_at=str(stat.st_mtime))


def delete_file(script_dir: Path, path: str, *, entrypoint: str) -> None:
    if path == entrypoint:
        raise ValueError("cannot delete entrypoint file")
    target = _resolve(script_dir, path)
    if not target.exists():
        raise FileNotFoundError(path)
    target.unlink()