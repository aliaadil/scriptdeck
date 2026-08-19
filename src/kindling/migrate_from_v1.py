"""Public entry point for the v1->v2 migration.

The CLI flag surface lives in :mod:`kindling.cli` (argparse) and the
implementation lives in :mod:`kindling.cli_commands.migrate`. This module
re-exports the migration runner so that downstream code can import a stable
name (``kindling.migrate_from_v1.run``) regardless of internal layout.

Data-format copy semantics are defined in ``cli_commands.migrate.run_async``
and are intentionally unchanged from v1: same four tables
(scripts, schedules, runs, logs), same column lists, ``INSERT OR IGNORE``
into the v2 DB.
"""
from __future__ import annotations

from kindling.cli_commands.migrate import run, run_async

__all__ = ["run", "run_async"]
