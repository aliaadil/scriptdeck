"""Shared validators for trigger params.

Both RunTrigger (POST /api/kindling/runs) and _ManualRunBody
(POST /api/kindling/scripts/{id}/run) accept the same params shape, so the
validation rules live here once and are reused.
"""
from __future__ import annotations

from typing import Any


def check_params_json(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a params_json dict: non-empty string keys, primitive values.

    Returns the value unchanged when valid; raises ValueError otherwise so a
    Pydantic field_validator surfaces the failure as a 422.
    """
    if v is None:
        return v
    for k, val in v.items():
        if not isinstance(k, str) or not k:
            raise ValueError("params_json keys must be non-empty strings")
        if not isinstance(val, (str, int, float, bool)):
            raise ValueError(f"params_json[{k!r}] must be a primitive")
    return v


def check_params_argv(v: list[Any] | None) -> list[str] | None:
    """Validate a params_argv list: every entry must be a string."""
    if v is None:
        return v
    if not isinstance(v, list):
        # Pydantic will type-check via list[str]; this guard is for callers
        # that pass Python values directly.
        raise ValueError("params_argv must be a list of strings")
    out: list[str] = []
    for i, t in enumerate(v):
        if not isinstance(t, str):
            raise ValueError(f"params_argv[{i}] must be a string, got {type(t).__name__}")
        out.append(t)
    return out


def check_params_exclusive(params_json: dict[str, Any] | None, params_argv: list[str] | None) -> None:
    """Reject callers who provide both forms in one request.

    They describe the same intent — the argv the script will receive — and
    letting both through lets disagreement of which one the runner honors.
    """
    if params_json is not None and params_argv is not None:
        raise ValueError(
            "Provide either params_json or params_argv, not both."
        )

