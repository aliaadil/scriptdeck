"""POST /api/kindling/webhooks/<token> — token-authenticated webhook trigger.

External callers (cron services, GitHub Actions, Stripe, etc.) fire a script
by POSTing to ``/api/kindling/webhooks/<token>``. No JWT is required — the
token in the URL is the sole credential.

Security model:
- The raw token is **never** persisted. The DB stores ``webhook_token_hash``,
  which is the SHA-256 hex digest of the token. Lookups hash the inbound
  token and compare.
- Bad tokens return 404 (not 401/403) to avoid disclosing whether the token
  exists in some form.
- Disabled triggers also return 404 for the same reason — the caller learns
  nothing from the response.
- Per-token rate limit: 60 requests / 60 seconds, enforced by an in-memory
  token bucket. Multi-worker deployments will need a Redis-backed limiter
  (out of scope; follow-up task).

On success:
- A run row is created with ``schedule_id`` set to the trigger's id, so the
  run groups with its trigger in the UI / audit.
- The trigger's ``params_json`` (if any) is exported into the run env as
  ``KINDLING_PARAM_<KEY>=<value>`` per key (see ``trigger_params_env``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import insert, select, update

from kindling.runner.executor import Script, run_script
from kindling.services import run_service
from kindling.services.dep_detect import detect_deps_for_language

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# --- Rate limiter (in-memory token bucket per token-hash) -------------------

# Default: 60 requests per 60 seconds, per SHA-256 token hash. Inbound tokens
# are hashed before lookup, so the limiter bucket key is the hash — one
# token can never affect another's bucket even if the hash collides (collision
# is astronomical; SHA-256).
_RATELIMIT_CAPACITY = 60
_RATELIMIT_WINDOW_SECONDS = 60

# Keyed by SHA-256 hex of the token (same value stored in the DB).
# Each entry is a deque of monotonic timestamps within the window.
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = asyncio.Lock()


def _token_bucket_consume(key: str, now: float | None = None) -> bool:
    """Synchronous core of the rate limiter — returns True if request may proceed.

    Acquire ``_rate_lock`` around this when called from async code (the
    webhooks endpoint does so). Keeping the inner work synchronous avoids
    awaiting inside the bucket pop.
    """
    ts = now if now is not None else time.monotonic()
    bucket = _rate_buckets[key]
    cutoff = ts - _RATELIMIT_WINDOW_SECONDS
    # Drop entries outside the window.
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= _RATELIMIT_CAPACITY:
        return False
    bucket.append(ts)
    return True


def reset_rate_limiter_for_tests() -> None:
    """Wipe all rate-limit state. Tests use this to start each scenario clean."""
    _rate_buckets.clear()


# --- Token utilities ---------------------------------------------------------


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a webhook token. The DB stores this,
    never the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- Env merge helper --------------------------------------------------------


def trigger_params_env(params_json: str | None) -> dict[str, str]:
    """Convert a trigger's ``params_json`` (a JSON object string) into the
    ``KINDLING_PARAM_<KEY>=<value>`` mapping that gets exported to the run env.

    Returns an empty dict when ``params_json`` is missing / blank. Booleans
    and numbers are stringified; everything else is rejected at the Pydantic
    layer so we don't need to defensively coerce at this boundary.
    """
    if not params_json:
        return {}
    try:
        parsed = json.loads(params_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or not k:
            continue
        out[f"KINDLING_PARAM_{k}"] = str(v)
    return out


# --- The endpoint ------------------------------------------------------------


@router.post("/{token}")
async def fire_webhook(token: str, request: Request):
    """Fire a webhook trigger. POST only (so curl --get / GET probes don't
    consume runs)."""
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    h = hash_token(token)
    async with _rate_lock:
        if not _token_bucket_consume(h):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )
    sf = request.app.state.session_factory
    async with sf() as s:
        # Look up by hash. If multiple rows share a hash (shouldn't happen —
        # unique partial index) we'd take whichever the DB returns first.
        # The unique partial index on webhook_token_hash enforces uniqueness
        # at the storage layer.
        from kindling.db.models import schedules as _schedules
        row = (await s.execute(
            select(_schedules).where(
                _schedules.c.webhook_token_hash == h,
                _schedules.c.kind == "webhook",
            )
        )).mappings().one_or_none()
        if row is None or not row["enabled"]:
            # 404 for both "no such token" and "disabled" — no information
            # disclosure.
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        script_id = int(row["script_id"])
        schedule_id = int(row["id"])
        params_env = trigger_params_env(row["params_json"])
        # Resolve the script row in the same session so we have language/path.
        from kindling.db.models import scripts as _scripts
        script_row = (await s.execute(
            select(_scripts).where(_scripts.c.id == script_id)
        )).mappings().one()
        # I1 from /runs: guard against concurrent trigger. Webhook callers
        # get 409 so they know to back off; the rate limiter will throttle
        # retry storms naturally.
        if await run_service.has_active_run(s, script_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="another run is in progress"
            )
        run_id, started_at, retry_group = await run_service.create_run(
            s, script_id=script_id, schedule_id=schedule_id,
        )
        # Always re-detect from source. The script_deps table is updated
        # so /deps reflects what's currently in use.
        storage = Path(request.app.state.settings.storage_dir)
        source_path = storage / script_row["source_path"]
        try:
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            source_text = ""
        deps = detect_deps_for_language(script_row["language"], source_text)
        now = datetime.now(UTC).isoformat()
        from kindling.db.models import script_deps as _deps_tbl
        existing_deps = (
            await s.execute(
                select(_deps_tbl).where(_deps_tbl.c.script_id == script_id)
            )
        ).mappings().one_or_none()
        if existing_deps:
            # Preserve a user-set manual entry; only auto-update rows that
            # were themselves auto-detected previously.
            if existing_deps["source"] != "manual":
                await s.execute(
                    update(_deps_tbl)
                    .where(_deps_tbl.c.script_id == script_id)
                    .values(deps_json=json.dumps(deps), source="auto", updated_at=now)
                )
        else:
            await s.execute(
                insert(_deps_tbl).values(
                    script_id=script_id,
                    deps_json=json.dumps(deps),
                    source="auto",
                    updated_at=now,
                )
            )
        await s.commit()
    # Schedule the background execution. We pass params_env via the env
    # ciphertext/none path? No — those are AES-encrypted blobs. The simplest
    # extension is to add a new kwarg to run_script. (See executor.py.)
    runner_script = Script(
        id=int(script_row["id"]), user_id=int(script_row["user_id"]),
        name=script_row["name"], language=script_row["language"],
        source_path=(storage / script_row["source_path"]).resolve(),
        entrypoint=script_row["entrypoint"],
        scripts_dir=storage / "scripts" / str(script_row["id"]),
        requirements=deps,
    )
    _schedule_execution(
        request.app,
        run_id=run_id,
        script=runner_script,
        params_env=params_env,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "schedule_id": schedule_id,
        "started_at": started_at,
        "retry_group": retry_group,
    }


def _schedule_execution(
    app,
    *,
    run_id: int,
    script: Script,
    params_env: dict[str, str],
) -> None:
    """Create and register the background run task."""
    import asyncio

    async def _run() -> None:
        try:
            await run_script(
                run_id=run_id,
                script=script,
                env_service=app.state.env_service,
                log_broker=app.state.log_broker,
                concurrency=app.state.runner_sem,
                storage_dir=Path(app.state.settings.storage_dir),
                active_procs=app.state.active_procs,
                param_env=params_env,
            )
        except Exception as exc:
            log.exception("webhook run_script raised for run_id=%s: %s", run_id, exc)

    task = asyncio.create_task(_run())
    app.state.background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        app.state.background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.exception("webhook background task failed: %s", exc)

    task.add_done_callback(_on_done)
