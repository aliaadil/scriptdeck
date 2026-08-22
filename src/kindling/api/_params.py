"""Shared validators for trigger params_json.

Both RunTrigger (POST /api/kindling/runs) and _ManualRunBody
(POST /api/kindling/scripts/{id}/run) accept the same params_json shape,
so the validation rules live here once and are reused.
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
