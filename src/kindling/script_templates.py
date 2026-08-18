"""Per-language starter templates for new scripts.

When a caller POSTs to /scripts with ``"template": "<lang>"``, ``seed_template``
writes a documented starter file for that language plus an empty ``.env`` into
the script directory. The DB ``entrypoint`` column is set to the canonical
filename (e.g. ``main.py`` for python, ``main.js`` for node, ``main.sh`` for
bash) so the runner can locate the entry point later.
"""
from __future__ import annotations

from pathlib import Path

PYTHON_MAIN = '''import os


def main() -> None:
    api_key = os.getenv("API_KEY", "")
    print(f"Hello from Kindling (api_key length: {len(api_key)})")


if __name__ == "__main__":
    main()
'''

NODE_MAIN = '''const apiKey = process.env.API_KEY || "";
console.log(`Hello from Kindling (api_key length: ${apiKey.length})`);
'''

BASH_MAIN = '''#!/usr/bin/env bash
set -euo pipefail
echo "Hello from Kindling (api_key length: ${#API_KEY:-0})"
'''

ENTRYPOINTS: dict[str, str] = {
    "python": "main.py",
    "node": "main.js",
    "bash": "main.sh",
}

SOURCES: dict[str, str] = {
    "python": PYTHON_MAIN,
    "node": NODE_MAIN,
    "bash": BASH_MAIN,
}


def seed_template(language: str, script_dir: Path) -> str:
    """Seed ``main.<ext>`` and an empty ``.env`` in ``script_dir``.

    Returns the entrypoint filename (e.g. ``"main.py"``).
    """
    if language not in ENTRYPOINTS:
        raise ValueError(f"unsupported language: {language}")
    script_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = ENTRYPOINTS[language]
    (script_dir / entrypoint).write_text(SOURCES[language], encoding="utf-8")
    env_path = script_dir / ".env"
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")
    return entrypoint
