"""CLI surface for `kindling migrate-from-v1`.

The migration entry point uses argparse (see src/kindling/cli.py), so this
test exercises the installed entry point as a subprocess and inspects the
--help output for the new flag names and defaults.
"""
from __future__ import annotations

import subprocess
import sys


def test_migrate_from_v1_help_lists_v2_flags(tmp_path):
    """`--v2-db-path` and `--v2-storage-path` must appear in --help output."""
    result = subprocess.run(
        [sys.executable, "-m", "kindling", "migrate-from-v1", "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"migrate-from-v1 --help failed: stderr={result.stderr!r}"
    )
    assert '--v2-db-path' in result.stdout, (
        f"expected --v2-db-path in help output, got: {result.stdout!r}"
    )
    assert '--v2-storage-path' in result.stdout, (
        f"expected --v2-storage-path in help output, got: {result.stdout!r}"
    )
    # Defaults should be advertised (kindling.db / ./storage), not required.
    assert 'kindling.db' in result.stdout, (
        f"expected kindling.db default in help output, got: {result.stdout!r}"
    )
    assert 'required' not in result.stdout.split('--v2-db-path')[1].split('--v2-storage-path')[0], (
        "--v2-db-path should not be required; check that the default is shown"
    )
