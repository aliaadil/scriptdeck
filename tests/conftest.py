"""Test fixtures: in-memory DB + temp storage for ScriptDeck."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the src/ layout importable without installing the package.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "scriptdeck.db"


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    d = tmp_path / "storage"
    d.mkdir(parents=True, exist_ok=True)
    return d