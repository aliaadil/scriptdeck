"""Command-line entry point for ``python -m scriptrunner``."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import Settings
from .importer import import_bugy
from .server import serve


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scriptdeck")
    subparsers = parser.add_subparsers(dest="command")
    import_parser = subparsers.add_parser("import", help="Import data from another script runner")
    import_parser.add_argument("format", choices=["bugy-script-server"])
    import_parser.add_argument("source_dir", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "import":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        settings = Settings.from_env()
        result = import_bugy(args.source_dir, settings.db_path, settings.storage_dir)
        print(json.dumps(result, sort_keys=True))
        return
    serve()


if __name__ == "__main__":
    main()
