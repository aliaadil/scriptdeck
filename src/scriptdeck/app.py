from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from scriptdeck.api.auth import router as auth_router
from scriptdeck.api.health import router as health_router
from scriptdeck.api.users import router as users_router
from scriptdeck.config import Settings
from scriptdeck.db import make_engine, run_migrations, run_migrations_sync
from scriptdeck.db.engine import session_factory as make_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings)
    Session = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(engine)
        app.state.engine = engine
        app.state.session_factory = Session
        app.state.settings = settings
        app.state.scheduler_running = False
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="ScriptDeck", version="2.0.0")
    # Eager state init + migrations so tests using ASGITransport (no lifespan)
    # still see a fully-initialized app. The lifespan handler above still runs
    # migrations idempotently and manages disposal in production.
    app.state.engine = engine
    app.state.session_factory = Session
    app.state.settings = settings
    app.state.scheduler_running = False
    app.router.lifespan_context = lifespan
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")

    # Apply migrations eagerly so tests (which don't trigger lifespan) see the
    # schema. `run_migrations_sync` is idempotent. In production the lifespan
    # handler will also call `run_migrations` (idempotent).
    run_migrations_sync(settings.db_path)
    return app


def run() -> None:
    import uvicorn

    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
