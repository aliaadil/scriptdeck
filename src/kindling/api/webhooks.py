"""Webhook triggers API (Issue #17).

Two route groups:

1. **Authed management** at ``/api/webhooks*`` — full CRUD, behind JWT.
   Same ownership scoping as scripts/schedules: non-admins only see
   webhooks on scripts they own.

2. **Public fire endpoint** at ``POST /webhooks/<token>`` — no JWT,
   token-in-path is the only credential. Anyone with the URL can fire
   the script. The operator regenerates the token if the URL leaks.

Both groups live in the same module because the URL shapes share a
prefix; splitting them felt like ceremony for ~50 lines of glue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from kindling.api.deps import require_script_owner
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.runner.executor import Script, run_script
from kindling.services import run_service, script_service, webhook_service

# Two routers — the authed CRUD one prefixes /api/webhooks, the public
# fire endpoint lives at /webhooks/<token> (no /api prefix) to make it
# visually distinct from the protected surface.
# The webhook router's prefix is just "/webhooks" because the app mounts
# it under the "/api/kindling" namespace. The nested per-script router
# declares its own full path so its URL shape ("/scripts/<id>/webhooks")
# survives even when mounted without a parent prefix.
router = APIRouter(prefix="/webhooks")
public_router = APIRouter(prefix="/webhooks")


def _table():
    from kindling.db.models import webhooks
    return webhooks


def _scripts_table():
    from kindling.db.models import scripts
    return scripts


class WebhookCreate(BaseModel):
    script_id: int
    description: str | None = Field(default=None, max_length=500)
    params: dict[str, str] | None = None
    enabled: bool = True


class WebhookCreateForScript(BaseModel):
    """Body for ``POST /scripts/<id>/webhooks`` — script_id comes from the URL."""

    description: str | None = Field(default=None, max_length=500)
    params: dict[str, str] | None = None
    enabled: bool = True


class WebhookPatch(BaseModel):
    # Issue #17: every field is optional, with None meaning "clear it"
    # (e.g. description=None clears the description). The router uses
    # ``exclude_unset`` so omitted fields are left alone; explicit
    # ``None`` is a real mutation.
    description: str | None = None
    enabled: bool | None = None
    params: dict[str, str] | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class WebhookOut(BaseModel):
    id: int
    script_id: int
    enabled: bool
    params: dict[str, str]
    description: str | None
    created_at: str
    last_fired_at: str | None
    fire_count: int


class WebhookCreated(WebhookOut):
    """Same as WebhookOut but also exposes the secret_token + full URL.

    Returned only on create + regenerate so the operator can copy the
    URL once; subsequent GETs strip it.
    """

    secret_token: str
    url: str | None = None


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


def _base_url(request: Request) -> str:
    """Compose the public base URL for echoing the webhook URL back to clients.

    Uses ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` when present so
    deployments behind a reverse proxy see the right scheme. Falls back
    to the request's own scheme + host for direct connections.
    """
    fproto = request.headers.get("x-forwarded-proto")
    fhost = request.headers.get("x-forwarded-host")
    scheme = fproto.split(",")[0].strip() if fproto else request.url.scheme
    host = fhost.split(",")[0].strip() if fhost else request.url.netloc
    return f"{scheme}://{host}"


def _own_script_ids_subquery(user: User):
    """Return a SQLAlchemy ``in_`` filter for scripts owned by ``user``.

    Admins skip the filter entirely (their GET sees everything); non-admin
    users get the equivalent of ``script_id IN (SELECT id FROM scripts
    WHERE user_id = :me)``.
    """
    from kindling.db.models import scripts as _scripts

    if user.role == "admin":
        return None
    return _scripts.c.user_id == user.id


@router.get("", response_model=list[WebhookOut])
async def list_endpoint(
    request: Request,
    script_id: int | None = None,
    user: User = Depends(current_user),
) -> list[WebhookOut]:
    """List webhooks, optionally filtered to one script.

    Non-admins only see webhooks on scripts they own — same scoping rule
    as the schedules list endpoint.
    """
    sf = request.app.state.session_factory
    t = _table()
    if script_id is not None:
        async with sf() as s:
            await require_script_owner(s, script_id, user)
        rows = await webhook_service.list_webhooks_for_script(s, script_id)
    else:
        async with sf() as s:
            if user.role != "admin":
                own = await s.execute(
                    select(_scripts_table().c.id).where(_scripts_table().c.user_id == user.id)
                )
                ids = [int(r[0]) for r in own.all()]
                rows = await webhook_service.list_webhooks(s, script_ids=ids)
            else:
                rows = await webhook_service.list_webhooks(s)
    return [WebhookOut(**webhook_service.row_to_out(r)) for r in rows]


# Per-script nested route for UI convenience. Returns the same payload as
# ``GET /api/webhooks?script_id=<id>`` but matches the URL shape the
# schedules UI already uses (``GET /api/scripts/<id>/schedules`` would
# be the symmetric counterpart; we expose it under the webhook module
# because that's where the CRUD lives).
nested_router = APIRouter(prefix="/scripts")


@nested_router.get("/{script_id}/webhooks", response_model=list[WebhookOut])
async def list_for_script(
    script_id: int, request: Request, user: User = Depends(current_user)
) -> list[WebhookOut]:
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        rows = await webhook_service.list_webhooks_for_script(s, script_id)
    return [WebhookOut(**webhook_service.row_to_out(r)) for r in rows]


@nested_router.post(
    "/{script_id}/webhooks", response_model=WebhookCreated, status_code=201
)
async def create_for_script(
    script_id: int,
    body: WebhookCreateForScript,
    request: Request,
    user: User = Depends(current_user),
) -> WebhookCreated:
    """Create a webhook with the script id taken from the URL."""
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await webhook_service.create_webhook(
            s,
            script_id=script_id,
            description=body.description,
            params=body.params,
            enabled=body.enabled,
        )
        await s.commit()
    out = webhook_service.row_with_token(row, base_url=_base_url(request))
    return WebhookCreated(**out)


@router.get("/{webhook_id}", response_model=WebhookOut)
async def get_endpoint(
    webhook_id: int, request: Request, user: User = Depends(current_user)
) -> WebhookOut:
    sf = request.app.state.session_factory
    async with sf() as s:
        row = await webhook_service.get_webhook(s, webhook_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await require_script_owner(s, int(row["script_id"]), user)
    return WebhookOut(**webhook_service.row_to_out(row))


@router.post("", response_model=WebhookCreated, status_code=201)
async def create(
    body: WebhookCreate, request: Request, user: User = Depends(current_user)
) -> WebhookCreated:
    """Create a webhook. Echoes the URL exactly once — store it client-side."""
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, body.script_id, user)
        row = await webhook_service.create_webhook(
            s,
            script_id=body.script_id,
            description=body.description,
            params=body.params,
            enabled=body.enabled,
        )
        await s.commit()
    out = webhook_service.row_with_token(row, base_url=_base_url(request))
    return WebhookCreated(**out)


@router.patch("/{webhook_id}", response_model=WebhookOut)
async def update(
    webhook_id: int,
    body: WebhookPatch,
    request: Request,
    user: User = Depends(current_user),
) -> WebhookOut:
    """Patch a webhook. Token rotation lives on ``/regenerate``."""
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        existing = await webhook_service.get_webhook(s, webhook_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await require_script_owner(s, int(existing["script_id"]), user)
        # ``exclude_unset`` keeps Pydantic from handing us fields the
        # caller didn't include; explicit ``null`` is a real mutation.
        patches = body.model_dump(exclude_unset=True)
        try:
            row = await webhook_service.update_webhook(
                s,
                webhook_id,
                updates=patches,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await s.commit()
    return WebhookOut(**webhook_service.row_to_out(row))


@router.post("/{webhook_id}/regenerate", response_model=WebhookCreated)
async def regenerate(
    webhook_id: int, request: Request, user: User = Depends(current_user)
) -> WebhookCreated:
    """Rotate the secret_token. Old URL stops working immediately."""
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        existing = await webhook_service.get_webhook(s, webhook_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await require_script_owner(s, int(existing["script_id"]), user)
        row = await webhook_service.regenerate_token(s, webhook_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await s.commit()
    out = webhook_service.row_with_token(row, base_url=_base_url(request))
    return WebhookCreated(**out)


@router.delete("/{webhook_id}", status_code=204)
async def remove(
    webhook_id: int, request: Request, user: User = Depends(current_user)
) -> Response:
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        existing = await webhook_service.get_webhook(s, webhook_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook not found")
        await require_script_owner(s, int(existing["script_id"]), user)
        await webhook_service.delete_webhook(s, webhook_id)
        await s.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------- public
# Below: the unauthenticated fire endpoint. Token-in-path is the only
# credential — there is intentionally no JWT, no Basic auth, no rate
# limit here. Per the spec the unguessable URL *is* the auth, and rate
# limiting is explicitly out of scope.


@public_router.post("/{token}", status_code=202)
async def fire(token: str, request: Request) -> dict:
    """Public fire endpoint. No JWT, no Basic — token is the credential.

    Behaviour mirrors the schedule-driven path: allocate a run row,
    schedule execution on the background task pool, return 202 with the
    new run_id. Returns 404 for unknown / disabled tokens — the operator
    treats "URL leak" by regenerating rather than giving a 410 that
    leaks which tokens once existed.
    """
    sf = request.app.state.session_factory
    async with sf() as s:
        webhook = await webhook_service.get_webhook_by_token(s, token)
        if webhook is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        script = await script_service.get_script(s, int(webhook["script_id"]))
        if script is None:
            # FK CASCADE should make this impossible; treat defensively.
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="script gone")
        # I1 guard: same as the authed trigger path.
        if await run_service.has_active_run(s, script.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="another run is in progress"
            )
        # We DON'T pass schedule_id (webhooks aren't schedules). The
        # RunOut shape still works because schedule_id is nullable.
        run_id, started, retry_group = await run_service.create_run(
            s, script_id=script.id, schedule_id=None
        )
        await webhook_service.record_fire(s, int(webhook["id"]))
        # Snapshot what the executor needs into locals so we don't keep
        # the session open across the await.
        storage = Path(request.app.state.settings.storage_dir)
        script_snapshot = Script(
            id=script.id,
            user_id=script.user_id,
            name=script.name,
            language=script.language,
            source_path=(storage / script.source_path).resolve(),
            entrypoint=script.entrypoint,
            scripts_dir=storage / "scripts" / str(script.id),
            requirements=[],
        )
        webhook_params = webhook_service.decode_params(webhook.get("params_json"))
        await s.commit()

    _schedule_webhook_execution(
        request.app,
        run_id=run_id,
        script=script_snapshot,
        params=webhook_params,
    )
    return {
        "run_id": run_id,
        "status": "running",
        "started_at": started,
    }


def _schedule_webhook_execution(
    app,
    *,
    run_id: int,
    script: Script,
    params: dict[str, str],
) -> None:
    """Drop the webhook-fired run on the same background pool the API uses.

    ``params`` are exported to the script as ``SCRIPTDECK_PARAM_<KEY>``
    plus a ``SCRIPTDECK_PARAMS_JSON`` blob, mirroring the contract the
    runner already uses for per-schedule params. This is the single
    place where webhook params become environment variables.
    """
    import asyncio
    import logging

    log = logging.getLogger(__name__)

    task = asyncio.create_task(
        _execute_webhook_run(
            run_id=run_id,
            script=script,
            app=app,
            params=params,
        )
    )
    app.state.background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        app.state.background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.exception("background webhook run failed: %s", exc)

    task.add_done_callback(_on_done)


async def _execute_webhook_run(*, run_id: int, script: Script, app, params: dict[str, str]) -> None:
    import logging

    log = logging.getLogger(__name__)
    try:
        result = await run_script(
            run_id=run_id,
            script=script,
            env_service=app.state.env_service,
            log_broker=app.state.log_broker,
            concurrency=app.state.runner_sem,
            storage_dir=app.state.settings.storage_dir_path,
            active_procs=app.state.active_procs,
            trigger_params=params,
        )
        status_str = "success" if result.exit_code == 0 else "failure"
    except Exception as exc:  # noqa: BLE001
        log.exception("webhook run_script raised for run_id=%s: %s", run_id, exc)
        try:
            await app.state.log_broker.close(run_id, "error", -1)
        except Exception:
            pass
        status_str = "error"
        result = type("R", (), {"exit_code": -1})()
    async with app.state.session_factory() as s:
        await run_service.finalize_run(s, run_id=run_id,
                                        exit_code=result.exit_code, status=status_str)
        await s.commit()


__all__ = ["router", "public_router", "nested_router"]
