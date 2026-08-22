"""Tests for the per-language params -> argv mapping used by manual runs.

Contract:
- python/bash: positional argv, JSON key insertion order; values str()'d.
- node: --key value pairs in JSON key insertion order; bool true -> --key,
  bool false -> key omitted entirely; non-bool values str()'d.
- raises ValueError for unsupported languages or non-dict input.
"""
from __future__ import annotations

import pytest

from kindling.params import argv_for


@pytest.mark.parametrize(
    "language,params,expected",
    [
        # Python/bash positional
        ("python", {"region": "us", "shard": 3}, ["us", "3"]),
        ("python", {}, []),
        ("bash", {"x": "y"}, ["y"]),
        ("bash", {"a": 1, "b": 2.5, "c": True}, ["1", "2.5", "True"]),
        # Node --key value
        ("node", {"region": "us", "shard": 3}, ["--region", "us", "--shard", "3"]),
        ("node", {}, []),
        # Node bool handling
        ("node", {"verbose": True, "debug": False}, ["--verbose"]),
        ("node", {"region": "us", "verbose": True}, ["--region", "us", "--verbose"]),
        # Insertion order preserved
        ("python", {"z": 1, "a": 2, "m": 3}, ["1", "2", "3"]),
    ],
)
def test_argv_for_supported(language, params, expected):
    assert argv_for(language, params) == expected


@pytest.mark.parametrize("language", ["ruby", "go", "", "PYTHON"])
def test_argv_for_unsupported_language_raises(language):
    with pytest.raises(ValueError):
        argv_for(language, {"x": "y"})


def test_argv_for_non_dict_raises():
    with pytest.raises(ValueError):
        argv_for("python", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        argv_for("python", ["x"])  # type: ignore[arg-type]
