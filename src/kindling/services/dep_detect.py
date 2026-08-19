from __future__ import annotations

import ast
import re
from importlib import resources


def _stdlib_set() -> set[str]:
    txt = (
        resources.files("kindling")
        .joinpath("data/python_stdlib.txt")
        .read_text(encoding="utf-8")
    )
    return {line.strip() for line in txt.splitlines() if line.strip()}


def _node_builtin_set() -> set[str]:
    txt = (
        resources.files("kindling")
        .joinpath("data/node_stdlib.txt")
        .read_text(encoding="utf-8")
    )
    return {line.strip() for line in txt.splitlines() if line.strip()}


def detect_python_deps(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    stdlib = _stdlib_set()
    return sorted(n for n in names if n and n not in stdlib)


_NODE_RE = re.compile(
    r"""(?:require\(\s*['"]([^'"]+)['"]\s*\)|from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|import\s+['"]([^'"]+)['"])"""
)


def detect_node_deps(source: str) -> list[str]:
    builtins = _node_builtin_set()
    out: set[str] = set()
    for match in _NODE_RE.finditer(source):
        spec = next(g for g in match.groups() if g)
        if spec.startswith((".", "/")):
            continue
        if spec.startswith("node:"):
            spec = spec[5:]
        root = spec.split("/")[0]
        if root.startswith("@"):
            parts = spec.split("/")
            if len(parts) >= 2:
                root = f"{parts[0]}/{parts[1]}"
        if root and root not in builtins:
            out.add(root)
    return sorted(out)


def detect_deps_for_language(language: str, source: str) -> list[str]:
    if language == "python":
        return detect_python_deps(source)
    if language == "node":
        return detect_node_deps(source)
    return []
