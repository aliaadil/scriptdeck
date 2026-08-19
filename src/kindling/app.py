from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kindling.api.admin import router as admin_router
from kindling.api.auth import router as auth_router
from kindling.api.deps import router as deps_router
from kindling.api.envs import router as envs_router
from kindling.api.health import router as health_router
from kindling.api.presets import router as presets_router
from kindling.api.runs import router as runs_router
from kindling.api.schedules import router as schedules_router
from kindling.api.scripts import router as scripts_router
from kindling.api.stats import router as stats_router
from kindling.api.users import router as users_router
from kindling.api.webhooks import nested_router as webhooks_nested_router
from kindling.api.webhooks import public_router as webhooks_public_router
from kindling.api.webhooks import router as webhooks_router
from kindling.config import Settings
from kindling.db import make_engine, run_migrations, run_migrations_sync
from kindling.db.engine import session_factory as make_session_factory
from kindling.scheduler.tick import scheduler_loop
from kindling.services.env_service import EnvService
from kindling.services.log_broker import get_broker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # Fail-fast on missing env encryption key. Bare-Python boots (no Docker
    # compose guarding via ${VAR:?required}) would otherwise fall back to a
    # zero-byte key and silently decrypt every .env blob with a key anyone
    # can compute. Tests opt out via allow_insecure_defaults_for_tests.
    if not settings.env_encryption_key and not settings.allow_insecure_defaults_for_tests:
        raise RuntimeError(
            "KINDLING_ENV_ENCRYPTION_KEY is required. Set it to a base64-encoded "
            "32-byte key (e.g. `python -c 'import os,base64;"
            "print(base64.b64encode(os.urandom(32)).decode())'`). "
            "For tests, construct Settings(..., allow_insecure_defaults_for_tests=True)."
        )
    engine = make_engine(settings)
    Session = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(engine)
        env_service = EnvService(settings.env_encryption_key)
        broker = get_broker()
        sem = asyncio.Semaphore(settings.runner_concurrency)
        stop_event = asyncio.Event()

        app.state.engine = engine
        app.state.session_factory = Session
        app.state.settings = settings
        app.state.env_service = env_service
        app.state.log_broker = broker
        app.state.runner_sem = sem
        app.state.stop_event = stop_event
        app.state.scheduler_running = True
        app.state.background_tasks: set[asyncio.Task] = set()
        app.state.active_procs: dict[int, asyncio.subprocess.Process] = {}

        task = asyncio.create_task(
            scheduler_loop(
                settings=settings,
                session_factory=Session,
                log_broker=broker,
                env_service=env_service,
                concurrency=sem,
                stop_event=stop_event,
                storage_dir=Path(settings.storage_dir),
                app=app,
            )
        )
        app.state.scheduler_task = task
        app.state.last_gc_at = None
        try:
            yield
        finally:
            stop_event.set()
            try:
                await asyncio.wait_for(task, timeout=5)
            except TimeoutError:
                task.cancel()
            await engine.dispose()

    app = FastAPI(title="Kindling", version="2.0.0", lifespan=lifespan)
    # Eager state init + migrations so tests using ASGITransport (no lifespan)
    # still see a fully-initialized app. The lifespan handler above still runs
    # migrations idempotently and manages disposal in production.
    broker = get_broker()
    app.state.engine = engine
    app.state.session_factory = Session
    app.state.settings = settings
    app.state.log_broker = broker
    # Eagerly init env_service if the supplied key is a valid 32-byte base64.
    # Tests sometimes pass placeholder keys (e.g. "A" * 44) that decode to the
    # wrong length; skip eager init in that case so test imports still work.
    # The lifespan handler re-validates the key on every real boot.
    try:
        app.state.env_service = EnvService(settings.env_encryption_key)
    except ValueError:
        pass
    app.state.scheduler_running = False
    app.state.background_tasks = set()
    app.state.active_procs = {}
    app.include_router(health_router, prefix="/api/kindling")
    app.include_router(auth_router, prefix="/api/kindling")
    app.include_router(users_router, prefix="/api/kindling")
    app.include_router(scripts_router, prefix="/api/kindling")
    app.include_router(deps_router, prefix="/api/kindling")
    app.include_router(envs_router, prefix="/api/kindling")
    app.include_router(schedules_router, prefix="/api/kindling")
    app.include_router(runs_router, prefix="/api/kindling")
    app.include_router(stats_router, prefix="/api/kindling")
    app.include_router(presets_router, prefix="/api/kindling")
    app.include_router(admin_router, prefix="/api/kindling")
    app.include_router(webhooks_router, prefix="/api/kindling")
    # Nested ``/api/kindling/scripts/<id>/webhooks`` lives at the same
    # prefix as the other scripts API; it owns its own router so the
    # webhook CRUD router doesn't have to special-case the URL shape.
    app.include_router(webhooks_nested_router, prefix="/api/kindling")
    # Public fire endpoint lives outside the /api/kindling prefix so it's
    # visually distinct from the JWT-protected API surface — operators
    # expect webhook URLs to look like https://host/webhooks/<token>.
    app.include_router(webhooks_public_router)

    # Apply migrations eagerly so tests (which don't trigger lifespan) see the
    # schema. `run_migrations_sync` is idempotent. In production the lifespan
    # handler will also call `run_migrations` (idempotent).
    run_migrations_sync(settings.db_path)

    # Mount dashboard static (Vite build output) if it has been produced.
    # In dev (no build yet) the directory is absent and the mount is skipped.
    dashboard_dir = Path(__file__).parent / "dashboard_static"
    if dashboard_dir.exists():
        # SPA fallback: any 404 inside /kindling serves index.html so deep links
        # like /kindling/dashboard or /kindling/runs/5 resolve client-side.
        # Real assets on disk still 404 if genuinely missing.
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        class KindlingSPA(StaticFiles):
            async def get_response(self, path, scope):
                # StaticFiles raises starlette.exceptions.HTTPException, which is
                # NOT a subclass of fastapi.HTTPException — catch the parent class
                # so we can intercept 404s and serve index.html instead.
                from starlette.exceptions import HTTPException as StarletteHTTPException

                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    index = Path(self.directory) / "index.html"
                    if not index.is_file():
                        raise
                    return FileResponse(index)

        app.mount("/kindling", KindlingSPA(directory=str(dashboard_dir), html=True), name="kindling")

        @app.get("/")
        async def root_redirect():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/kindling/")

        # Top-level SPA catch-all: any other unmatched path (excluding /api and
        # /kindling, which are handled above) also serves index.html so an
        # in-app navigation that lost its prefix still lands somewhere sane.
        @app.get("/{path:path}")
        async def spa_catch_all(path: str):
            if path.startswith("api/") or path.startswith("kindling/"):
                raise HTTPException(status_code=404)
            asset_file = dashboard_dir / path
            if asset_file.is_file():
                return FileResponse(asset_file)
            index_file = dashboard_dir / "index.html"
            if not index_file.exists():
                raise HTTPException(status_code=404)
            return FileResponse(index_file)
    return app


def run() -> None:
    import uvicorn

    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
