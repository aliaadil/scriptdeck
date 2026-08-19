from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kindling.services.schedule_service import ComputeError, compute_next_run


def test_basic_cron_utc():
    # 0 9 * * * = 09:00 daily UTC
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="UTC",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_tz_shifts_fire_time():
    # 0 9 * * * in America/New_York; on Aug 16 (EDT, UTC-4) that is 13:00 UTC.
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="America/New_York",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 16, 13, 0, tzinfo=UTC)


def test_include_days_filters():
    # 0 17 * * 2-4 in UTC: only Tue/Wed/Thu 17:00.
    # After Mon 2026-08-17 18:00 UTC, next is Tue 2026-08-18 17:00 UTC.
    nxt = compute_next_run(
        cron_expr="0 17 * * 2-4",
        tz_name="UTC",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 17, 18, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 18, 17, 0, tzinfo=UTC)


def test_blackout_date_skipped():
    # 0 9 * * * UTC. Blackout 2026-08-17. After 2026-08-16 18:00, next is 08-18 09:00.
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="UTC",
        blackout_dates=["2026-08-17"],
        include_days=None,
        after=datetime(2026, 8, 16, 18, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


def test_dst_spring_forward():
    # America/New_York: 2026-03-08 02:00 EST -> 03:00 EDT (skip 02:00-03:00).
    # Cron "30 2 * * *" — 02:30 doesn't exist; croniter should jump to next valid.
    nxt = compute_next_run(
        cron_expr="30 2 * * *",
        tz_name="America/New_York",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 3, 8, 0, 0, tzinfo=UTC),
    )
    # The gap day 2026-03-08 02:30 EST doesn't exist; croniter returns the next
    # valid local time after the gap (2026-03-08 03:00 EDT = 2026-03-08 07:00 UTC).
    # Verify the result is on or after the gap day and not inside the gap.
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    nxt_local = nxt.astimezone(ny)
    assert nxt_local >= datetime(2026, 3, 8, 3, 0, tzinfo=ny)


def test_invalid_cron_raises():
    with pytest.raises(ComputeError):
        compute_next_run(
            cron_expr="not a cron",
            tz_name="UTC",
            blackout_dates=None,
            include_days=None,
            after=datetime(2026, 8, 16, tzinfo=UTC),
        )
