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
    """Validate `path` and return its resolved absolute path inside `script_dir`.

    The returned path is **not** confirmed to exist — use `resolve(strict=True)`
    at the call site when performing read/delete so a symlink cannot be
    swapped in between validation and use (TOCTOU).
    """
    validated = validate_path(path)
    script_root = script_dir.resolve()
    target = (script_root / validated).resolve()
    # is_relative_to handles the prefix-bypass case
    # (e.g. /tmp/foo vs /tmp/foo_bar/x) that startswith misses.
    if not target.is_relative_to(script_root):
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
        entries.append(FileEntry(path=rel, size=stat.st_size, updated_at=str(stat.st_mtime)))
    # Entrypoint first
    entries.sort(key=lambda e: (e.path != entrypoint, e.path))
    return entries


def read_file(script_dir: Path, path: str) -> str:
    # resolve(strict=True) raises FileNotFoundError if the path doesn't
    # exist, and crucially resolves symlinks atomically — closing the
    # TOCTOU window between validation and the read.
    target = _resolve(script_dir, path).resolve(strict=True)
    return target.read_text(encoding="utf-8")


def write_file(script_dir: Path, path: str, content: str) -> FileEntry:
    target = _resolve(script_dir, path)
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
    # Resolve the parent directory so that any symlink swap below this
    # point redirects into content the user didn't intend. We then
    # create the file (don't follow a pre-existing symlink at `target`).
    parent = target.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    target.write_text(content, encoding="utf-8")
    stat = target.stat()
    return FileEntry(path=path, size=stat.st_size, updated_at=str(stat.st_mtime))


def delete_file(script_dir: Path, path: str, *, entrypoint: str) -> None:
    if path == entrypoint:
        raise ValueError("cannot delete entrypoint file")
    # resolve(strict=True) raises FileNotFoundError if the path doesn't
    # exist, and resolves symlinks atomically (closing the TOCTOU window).
    target = _resolve(script_dir, path).resolve(strict=True)
    # Re-validate after the final resolve in case the symlink now points
    # outside script_dir (defense-in-depth against race).
    script_root = script_dir.resolve()
    if not target.is_relative_to(script_root):
        raise ValueError("path escapes script directory")
    target.unlink()
