"""Map a manual-run params dict to language-appropriate argv.

The mapping is intentionally simple so scripts can rely on the conventional
CLI shape for their language:

- python/bash: positional argv in JSON key insertion order. Keys are
  ignored; values are str()'d. ``argv_for("python", {"region": "us"})``
  returns ``["us"]`` and the runner appends after the entrypoint, so the
  script sees ``sys.argv == ["main.py", "us"]``.
- node: ``--key value`` pairs in JSON key insertion order. Booleans are
  special: ``true`` becomes just ``--key`` (the conventional flag-only
  form); ``false`` omits the key entirely (a way to spell "leave it
  off" without removing it from the dict).

The ``KINDLING_PARAM_<KEY>=<value>`` env-var export (see
``trigger_params_env`` in ``kindling.api.webhooks``) happens in addition
to argv, unchanged from the trigger path.
"""
from __future__ import annotations

from typing import Any

_SUPPORTED = {"python", "bash", "node"}


def argv_for(language: str, params: dict[str, Any] | None) -> list[str]:
    """Return the argv to append after the script entrypoint.

    Raises ValueError for non-dict input or unsupported ``language``.
    Returns ``[]`` for ``None`` / empty dict — the runner behaves the
    same as a no-params call today.
    """
    if not isinstance(params, dict):
        raise ValueError(f"params must be a dict, got {type(params).__name__}")
    if language not in _SUPPORTED:
        raise ValueError(
            f"unsupported language for argv_for: {language!r} "
            f"(expected one of {sorted(_SUPPORTED)})"
        )
    if language == "node":
        out: list[str] = []
        for k, v in params.items():
            if v is False:
                continue
            out.append(f"--{k}")
            if not isinstance(v, bool):
                out.append(str(v))
        return out
    # python / bash: positional, key order preserved
    return [str(v) for v in params.values()]
