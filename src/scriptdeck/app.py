from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scriptdeck.api.admin import router as admin_router
from scriptdeck.api.auth import router as auth_router
from scriptdeck.api.deps import router as deps_router
from scriptdeck.api.envs import router as envs_router
from scriptdeck.api.health import router as health_router
from scriptdeck.api.runs import router as runs_router
from scriptdeck.api.schedules import router as schedules_router
from scriptdeck.api.scripts import router as scripts_router
from scriptdeck.api.stats import router as stats_router
from scriptdeck.api.users import router as users_router
from scriptdeck.config import Settings
from scriptdeck.db import make_engine, run_migrations, run_migrations_sync
from scriptdeck.db.engine import session_factory as make_session_factory
from scriptdeck.scheduler.tick import scheduler_loop
from scriptdeck.services.env_service import EnvService
from scriptdeck.services.log_broker import get_broker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings)
    Session = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(engine)
        env_service = EnvService(
            settings.env_encryption_key or base64.b64encode(b"\0" * 32).decode()
        )
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
        try:
            yield
        finally:
            stop_event.set()
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
            await engine.dispose()

    app = FastAPI(title="ScriptDeck", version="2.0.0")
    # Eager state init + migrations so tests using ASGITransport (no lifespan)
    # still see a fully-initialized app. The lifespan handler above still runs
    # migrations idempotently and manages disposal in production.
    broker = get_broker()
    app.state.engine = engine
    app.state.session_factory = Session
    app.state.settings = settings
    app.state.log_broker = broker
    # Eagerly init env_service only if the key is present and valid; otherwise
    # defer to first use so tests with placeholder keys (e.g. "A" * 44) still
    # load the app. The lifespan handler always re-runs init for production.
    env_key = settings.env_encryption_key
    if env_key:
        try:
            app.state.env_service = EnvService(env_key)
        except ValueError:
            pass
    app.state.scheduler_running = False
    app.state.background_tasks = set()
    app.state.active_procs = {}
    app.router.lifespan_context = lifespan
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(scripts_router, prefix="/api")
    app.include_router(deps_router, prefix="/api")
    app.include_router(envs_router, prefix="/api")
    app.include_router(schedules_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(stats_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    # Apply migrations eagerly so tests (which don't trigger lifespan) see the
    # schema. `run_migrations_sync` is idempotent. In production the lifespan
    # handler will also call `run_migrations` (idempotent).
    run_migrations_sync(settings.db_path)

    # Mount dashboard static (Vite build output) if it has been produced.
    # In dev (no build yet) the directory is absent and the mount is skipped.
    dashboard_dir = Path(__file__).parent / "dashboard_static"
    if dashboard_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

        @app.get("/")
        async def root_redirect():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/dashboard/")

        # SPA catch-all: serve index.html for any client-side path that did
        # not match /api/* or /dashboard/*. Routes are matched in registration
        # order, so the explicit routes above take precedence.
        @app.get("/{path:path}")
        async def spa_catch_all(path: str):
            from fastapi.responses import FileResponse

            # Exclude any path that begins with api/ or dashboard/ explicitly.
            if path.startswith("api/") or path.startswith("dashboard/"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404)
            index_file = dashboard_dir / "index.html"
            if not index_file.exists():
                from fastapi import HTTPException

                raise HTTPException(status_code=404)
            return FileResponse(index_file)
    return app


def run() -> None:
    import uvicorn

    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
