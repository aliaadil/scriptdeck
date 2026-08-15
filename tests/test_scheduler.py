import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


@pytest.mark.asyncio
async def test_tick_due_schedule_dispatches(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    now = datetime.now(timezone.utc).isoformat()

    from scriptdeck.db.models import schedules, scripts

    async with Sf() as s:
        await s.execute(
            insert(scripts).values(
                id=1,
                name="t",
                language="python",
                source_path="scripts/1/main.py",
            )
        )
        await s.execute(
            insert(schedules).values(
                script_id=1, kind="interval", expression="5m", next_run_at=now
            )
        )
        await s.commit()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw):
            return {}

    await _tick(
        settings=settings,
        session_factory=Sf,
        log_broker=broker,
        env_service=FakeEnv(),
        concurrency=sem,
        storage_dir=tmp_path / "s",
    )
    await asyncio.sleep(2)

    async with Sf() as s:
        rows = (await s.execute(text("SELECT status FROM runs"))).all()
    statuses = [r[0] for r in rows]
    assert "success" in statuses
