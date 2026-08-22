"""Unit tests for services.install — package-name validation and the
log-parser used by the RunView InstallForm.

The shell-out path is exercised separately by
``tests/api/test_install_endpoint.py`` (with the function patched); here
we only test the pure-Python helpers so the suite stays fast and free
of the ``uv`` / ``npm`` host requirement.
"""
from __future__ import annotations

import pytest

from kindling.services.install import detect_missing_modules


def test_detect_python_module_not_found():
    text = (
        "Traceback (most recent call last):\n"
        "  File \"main.py\", line 1, in <module>\n"
        "    import boto3\n"
        "ModuleNotFoundError: No module named 'boto3'\n"
    )
    assert detect_missing_modules(text) == ["boto3"]


def test_detect_python_dotted_module_uses_top_level():
    """``from boto3.session import Session`` -> suggest ``boto3``."""
    text = "ModuleNotFoundError: No module named 'boto3.session'"
    assert detect_missing_modules(text) == ["boto3"]


def test_detect_node_cannot_find_module():
    text = "Error: Cannot find module 'lodash'\n"
    assert detect_missing_modules(text) == ["lodash"]


def test_detect_node_scoped_package_keeps_scope():
    """``@types/node`` installs as-is, not as ``@types``."""
    text = "Cannot find module '@types/node'"
    assert detect_missing_modules(text) == ["@types/node"]


def test_detect_node_subpath_uses_top_segment():
    """``lodash/foo`` -> suggest ``lodash``."""
    text = "Cannot find module 'lodash/fp'"
    assert detect_missing_modules(text) == ["lodash"]


def test_detect_dedupes():
    text = (
        "ModuleNotFoundError: No module named 'boto3'\n"
        "ModuleNotFoundError: No module named 'boto3.session'\n"
        "ModuleNotFoundError: No module named 'boto3'\n"
    )
    assert detect_missing_modules(text) == ["boto3"]


def test_detect_empty_output():
    assert detect_missing_modules("") == []


def test_detect_irrelevant_lines_ignored():
    assert detect_missing_modules("hello world\nno error here\n") == []


def test_install_packages_rejects_unsafe_names():
    """Service-layer regex must reject shell-metacharacter-y inputs even
    if the API validator is bypassed (e.g. a future internal caller)."""
    import asyncio
    from pathlib import Path

    from kindling.services.install import install_packages

    async def run():
        with pytest.raises(ValueError, match="invalid package name"):
            await install_packages(
                language="python",
                user_id=1,
                script_id=1,
                storage_dir=Path("/tmp"),
                packages=["ok; rm -rf /"],
            )

    asyncio.run(run())


def test_install_packages_rejects_empty():
    import asyncio
    from pathlib import Path

    from kindling.services.install import install_packages

    async def run():
        with pytest.raises(ValueError, match="no packages"):
            await install_packages(
                language="python",
                user_id=1,
                script_id=1,
                storage_dir=Path("/tmp"),
                packages=[],
            )

    asyncio.run(run())


def test_install_packages_rejects_bash():
    import asyncio
    from pathlib import Path

    from kindling.services.install import install_packages

    async def run():
        with pytest.raises(ValueError, match="language='bash'"):
            await install_packages(
                language="bash",
                user_id=1,
                script_id=1,
                storage_dir=Path("/tmp"),
                packages=["foo"],
            )

    asyncio.run(run())
