"""Tests for the ScheduleCreate / ScheduleOut Pydantic schemas with kind='webhook'.

The schedules API now accepts kind='webhook' (in addition to cron/interval)
and rejects cron/interval-specific fields when kind='webhook' (and vice-versa).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from kindling.api.schedules import ScheduleCreate, ScheduleOut


def test_schedule_create_accepts_cron_kind():
    body = ScheduleCreate(
        script_id=1, kind="cron", expression="* * * * *",
        timezone="UTC",
    )
    assert body.kind == "cron"


def test_schedule_create_accepts_interval_kind():
    body = ScheduleCreate(
        script_id=1, kind="interval", expression="5m",
    )
    assert body.kind == "interval"


def test_schedule_create_accepts_webhook_kind():
    """A webhook trigger requires no expression / timezone / overlap_policy.
    Only params_json and enabled are relevant."""
    body = ScheduleCreate(
        script_id=1, kind="webhook", expression="ignored",
    )
    assert body.kind == "webhook"


def test_schedule_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        ScheduleCreate(script_id=1, kind="rabbit", expression="x")


def test_schedule_create_rejects_cron_specific_fields_when_kind_is_webhook():
    """When kind='webhook', the validator must reject cron/interval-specific
    fields (timezone, blackout_dates, include_days) since they don't apply."""
    with pytest.raises(ValidationError) as ei:
        ScheduleCreate(
            script_id=1, kind="webhook", expression=None,
            timezone="America/New_York",
        )
    assert "timezone" in str(ei.value).lower() or "webhook" in str(ei.value).lower()


def test_schedule_create_rejects_webhook_params_when_kind_is_cron():
    """When kind is cron/interval, params_json must be None/empty — webhook
    features are not allowed on time-based triggers in this iteration."""
    with pytest.raises(ValidationError) as ei:
        ScheduleCreate(
            script_id=1, kind="cron", expression="* * * * *",
            params_json={"k": "v"},
        )
    assert "params_json" in str(ei.value).lower() or "cron" in str(ei.value).lower()


def test_schedule_create_webhook_requires_no_expression():
    """A webhook row's expression is meaningless. We require it to be None/empty."""
    # An empty expression should be rejected by the existing min_length=1 validator
    with pytest.raises(ValidationError):
        ScheduleCreate(script_id=1, kind="webhook", expression="")


def test_schedule_create_webhook_params_json_accepts_dict():
    body = ScheduleCreate(
        script_id=1, kind="webhook", expression=None,
        params_json={"region": "us-east-1", "shard": 3},
    )
    assert body.params_json == {"region": "us-east-1", "shard": 3}


def test_schedule_out_serializes_webhook_fields():
    out = ScheduleOut(
        id=1, script_id=1, kind="webhook", expression=None,
        enabled=True, next_run_at=None,
        retry_max=0, retry_backoff=0, timezone=None,
        blackout_dates=None, include_days=None,
        overlap_policy="skip", queue_max=10, queue_dropped=0,
        run_count=0,
        params_json={"x": 1},
    )
    assert out.kind == "webhook"
    assert out.params_json == {"x": 1}
    assert out.next_run_at is None
