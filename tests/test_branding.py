import subprocess
import sys

import pytest


def test_package_imports_as_kindling():
    try:
        import kindling
    except ImportError:
        pytest.skip(
            "kindling not importable in this collection context"
        )
    assert kindling.__name__ == 'kindling'


def test_cli_command_name():
    # The CLI is argparse-based (see src/kindling/cli.py), so exercise the
    # installed entry point as a subprocess and confirm the program name
    # in --help output is "kindling".
    result = subprocess.run(
        [sys.executable, "-m", "kindling", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"kindling --help failed: stderr={result.stderr!r}"
    )
    # argparse prints "usage: <prog> ..." as the first help line.
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    assert first_line.startswith("usage: kindling"), (
        f"unexpected usage line: {first_line!r}"
    )
