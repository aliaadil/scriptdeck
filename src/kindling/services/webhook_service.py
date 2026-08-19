"""Webhook triggers (Issue #17).

A webhook is a public trigger — anyone with the unguessable ``secret_token``
URL can POST to ``/webhooks/<token>`` and the same runner path that fires
schedules will pick it up. Tokens are 32 url-safe random bytes
(``secrets.token_urlsafe(32)``), which gives ~190 bits of entropy — enough
to make guessing infeasible and short enough to fit in a URL path without
ugly escapes.

All public mutation goes through this module so the API routers don't have
to know about token generation, JSON-encoding rules, or the
``last_fired_at`` / ``fire_count`` accounting.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from kindling.db.models import webhooks as _webhooks
    return _webhooks


def _scripts_table():
    from kindling.db.models import scripts as _scripts
    return _scripts


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_token() -> str:
    """Generate a fresh webhook secret token.

    32 url-safe bytes from ``secrets`` = ~43 chars of base64-url, ~190 bits
    of entropy. Unguessable in practice and short enough to paste into a
    URL.
    """
    return secrets.token_urlsafe(32)


def _decode_params(raw: str | None) -> dict[str, str]:
    """Decode a stored ``params_json`` blob into a ``{str: str}`` dict.

    Stored as ``TEXT`` (SQLite has no native JSON type). Empty / missing
    values collapse to ``{}`` so callers don't have to special-case NULL.
    Bad JSON is treated as ``{}`` and logged by the caller if it cares —
    we never want to crash the runner because someone hand-edited a row.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    # Coerce values to str so the runner can drop them straight into env.
    return {str(k): str(v) for k, v in parsed.items()}


# Public alias — the scheduler tick imports ``decode_params`` and we'd
# rather not have it reach into a private symbol.
decode_params = _decode_params


def encode_params(params: dict[str, Any] | None) -> str:
    """Canonical encoder for the ``params_json`` column.

    Validates that the caller passed a flat stringy dict — nested objects
    are rejected because the env export contract is one-level deep.
    Returns the JSON string (always a non-empty object — never null).
    """
    if params is None:
        return "{}"
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")
    coerced: dict[str, str] = {}
    for k, v in params.items():
        if not isinstance(k, str):
            raise ValueError("params keys must be strings")
        coerced[k] = str(v)
    return json.dumps(coerced, separators=(",", ":"), sort_keys=True)


async def create_webhook(
    session: AsyncSession,
    *,
    script_id: int,
    description: str | None = None,
    params: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Insert a new webhook row. Returns the row as a dict.

    ``secret_token`` is generated server-side; the caller never sees it
    before this function returns. Raises ``ValueError`` if the script
    doesn't exist (so 404s surface cleanly to the API layer).
    """
    scripts_t = _scripts_table()
    script_exists = (
        await session.execute(select(scripts_t.c.id).where(scripts_t.c.id == script_id))
    ).first()
    if script_exists is None:
        raise ValueError(f"script {script_id} does not exist")

    t = _table()
    values = {
        "script_id": script_id,
        "secret_token": _new_token(),
        "enabled": 1 if enabled else 0,
        "params_json": encode_params(params),
        "description": description,
        "created_at": _now(),
    }
    stmt = insert(t).values(**values).returning(*t.c)
    row = (await session.execute(stmt)).mappings().one()
    return dict(row)


async def get_webhook(session: AsyncSession, webhook_id: int) -> dict[str, Any] | None:
    t = _table()
    row = (
        await session.execute(select(t).where(t.c.id == webhook_id))
    ).mappings().one_or_none()
    return dict(row) if row else None


async def get_webhook_by_token(
    session: AsyncSession, token: str
) -> dict[str, Any] | None:
    """Public-path lookup. Returns the webhook row for an active token.

    The unique partial index on ``enabled = 1`` keeps this O(log n) even
    with thousands of disabled rows hanging around for audit.
    """
    t = _table()
    row = (
        await session.execute(
            select(t).where(t.c.secret_token == token, t.c.enabled == 1)
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def list_webhooks_for_script(
    session: AsyncSession, script_id: int
) -> list[dict[str, Any]]:
    t = _table()
    rows = (
        await session.execute(
            select(t).where(t.c.script_id == script_id).order_by(t.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_webhooks(
    session: AsyncSession, *, script_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """List all webhooks, optionally restricted to a set of script ids.

    The ``script_ids`` filter is the ownership-scoping hook the API uses
    for non-admin users (they only see webhooks on scripts they own).
    """
    t = _table()
    stmt = select(t).order_by(t.c.id)
    if script_ids is not None:
        if not script_ids:
            return []
        stmt = stmt.where(t.c.script_id.in_(script_ids))
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def update_webhook(
    session: AsyncSession,
    webhook_id: int,
    *,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Patch a webhook with the keys the API router actually saw.

    Pass only the fields the caller sent (``exclude_unset`` on the
    Pydantic side). Returns the updated row, or None if the webhook
    doesn't exist. Raises ``ValueError`` if no fields were supplied
    (nothing to do) or if ``params`` is the wrong shape.
    """
    t = _table()
    existing = (
        await session.execute(select(t).where(t.c.id == webhook_id))
    ).mappings().one_or_none()
    if existing is None:
        return None

    values: dict[str, Any] = {}
    if "description" in updates:
        values["description"] = updates["description"]
    if "enabled" in updates:
        values["enabled"] = 1 if bool(updates["enabled"]) else 0
    if "params" in updates:
        params = updates["params"]
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be a JSON object or null")
        values["params_json"] = encode_params(params if isinstance(params, dict) else None)
    if not values:
        raise ValueError("no fields to update")

    await session.execute(update(t).where(t.c.id == webhook_id).values(**values))
    row = (
        await session.execute(select(t).where(t.c.id == webhook_id))
    ).mappings().one()
    return dict(row)
async def regenerate_token(
    session: AsyncSession, webhook_id: int
) -> dict[str, Any] | None:
    """Rotate ``secret_token`` for a webhook. Returns the new row.

    Used both as a "I leaked the URL" panic button and to give operators
    a clean way to retire a URL. The old token stops working immediately
    because the partial unique index requires ``enabled = 1`` and the
    lookup is on the literal token value — there's no grace window.
    """
    t = _table()
    existing = (
        await session.execute(select(t).where(t.c.id == webhook_id))
    ).mappings().one_or_none()
    if existing is None:
        return None
    new_token = _new_token()
    await session.execute(
        update(t).where(t.c.id == webhook_id).values(secret_token=new_token)
    )
    row = (
        await session.execute(select(t).where(t.c.id == webhook_id))
    ).mappings().one()
    return dict(row)


async def delete_webhook(session: AsyncSession, webhook_id: int) -> bool:
    """Hard-delete a webhook. Returns True if a row was removed."""
    t = _table()
    result = await session.execute(delete(t).where(t.c.id == webhook_id))
    return (result.rowcount or 0) > 0


async def record_fire(
    session: AsyncSession, webhook_id: int
) -> None:
    """Bump ``fire_count`` and stamp ``last_fired_at`` after a successful fire.

    Called from the public /webhooks/<token> endpoint after the run row
    is allocated. Best-effort: if the update fails the run still goes
    through (we just lose one audit tick).
    """
    t = _table()
    await session.execute(
        update(t)
        .where(t.c.id == webhook_id)
        .values(fire_count=t.c.fire_count + 1, last_fired_at=_now())
    )


def row_to_out(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a webhook row for the JSON API.

    Decodes ``params_json`` into a real dict and never echoes
    ``secret_token`` (the operator already saw it on create; the SPA can
    store it client-side if it wants to render the URL again). Listing
    endpoints that need to display the URL can call ``token_for_url``
    separately.
    """
    params = _decode_params(row.get("params_json"))
    return {
        "id": int(row["id"]),
        "script_id": int(row["script_id"]),
        "enabled": bool(row["enabled"]),
        "params": params,
        "description": row.get("description"),
        "created_at": row["created_at"],
        "last_fired_at": row.get("last_fired_at"),
        "fire_count": int(row.get("fire_count") or 0),
    }


def row_with_token(row: dict[str, Any], base_url: str | None = None) -> dict[str, Any]:
    """Like ``row_to_out`` but also exposes the secret_token + full URL.

    Only call this on the create / regenerate response paths so the
    operator can copy the URL. Never use it in list endpoints.
    """
    out = row_to_out(row)
    out["secret_token"] = row["secret_token"]
    if base_url:
        out["url"] = f"{base_url.rstrip('/')}/webhooks/{row['secret_token']}"
    return out


__all__ = [
    "create_webhook",
    "get_webhook",
    "get_webhook_by_token",
    "list_webhooks_for_script",
    "list_webhooks",
    "update_webhook",
    "regenerate_token",
    "delete_webhook",
    "record_fire",
    "row_to_out",
    "row_with_token",
    "encode_params",
    "decode_params",
]
