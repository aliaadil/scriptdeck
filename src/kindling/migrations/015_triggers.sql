-- Migration 015: per-script triggers.
--
-- Extend ``schedules`` to also hold webhook triggers (the spec calls these
-- "triggers" — a single script can have multiple cron/interval schedules
-- AND one or more webhook triggers, each independently enqueuing a run).
--
-- Trade-off vs. a separate ``triggers`` table:
--   + Webhook triggers want the same per-script machinery as cron/interval
--     rows: script_id FK + ON DELETE CASCADE, overlap_policy / retry_max,
--     enabled flag, and the runs.schedule_id FK that groups runs in the UI
--     and audit trail. Reusing ``schedules`` keeps all of that.
--   + Webhook rows simply have next_run_at = NULL and are never picked up by
--     the scheduler tick (the tick filters kind IN ('cron','interval')).
--   + ``/api/kindling/schedules`` endpoints stay unchanged for users who
--     don't adopt webhook triggers — the change is purely additive.
--   - One nullable ``expression`` column on rows where it's meaningless
--     (webhook). Acceptable; expression carries the webhook token reference
--     when the row is needed for debug, and it's just TEXT storage.
--
-- New columns:
--   params_json        TEXT — JSON object of per-trigger params; merged into
--                            the run env as KINDLING_PARAM_<KEY>=<value>.
--   webhook_token_hash TEXT — SHA-256 hex of the secret token used for
--                            POST /webhooks/<token>. NULL for non-webhook
--                            rows. Unique when set so duplicate-token
--                            collision is impossible.
--
-- Schema tweaks:
--   - Widen schedules.kind CHECK to include 'webhook'.
--   - Make next_run_at nullable (webhook rows have no scheduled fire time).
--   - Make expression nullable (webhook rows have no cron/interval expr;
--     the webhook URL token is the "expression"). The ``003_schedules``
--     and ``011_schedules_runs_v2`` migrations declared both NOT NULL.

-- Widen schedules.kind CHECK to include 'webhook', and allow next_run_at +
-- expression to be NULL (webhook rows have neither).
-- SQLite cannot ALTER a column's nullability or modify a CHECK; rebuild
-- the whole table. The CREATE TABLE below replaces the old schema.
CREATE TABLE schedules_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    expression TEXT,                  -- nullable: webhook rows have no expression
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT,                 -- nullable: webhook rows have no next_run_at
    retry_max INTEGER NOT NULL DEFAULT 0,
    retry_backoff INTEGER NOT NULL DEFAULT 0,
    last_status TEXT,
    last_error TEXT,
    timezone TEXT,
    blackout_dates TEXT,
    include_days TEXT,
    overlap_policy TEXT NOT NULL DEFAULT 'skip',
    queue_max INTEGER NOT NULL DEFAULT 10,
    queue_dropped INTEGER NOT NULL DEFAULT 0,
    params_json TEXT,                 -- per-trigger params, JSON object
    webhook_token_hash TEXT,          -- SHA-256 hex of webhook secret; nullable
    CHECK (kind IN ('cron', 'interval', 'webhook'))
);
INSERT INTO schedules_new (
    id, script_id, kind, expression, enabled, next_run_at,
    retry_max, retry_backoff, last_status, last_error,
    timezone, blackout_dates, include_days,
    overlap_policy, queue_max, queue_dropped
) SELECT
    id, script_id, kind, expression, enabled, next_run_at,
    retry_max, retry_backoff, last_status, last_error,
    timezone, blackout_dates, include_days,
    overlap_policy, queue_max, queue_dropped
FROM schedules;
DROP TABLE schedules;
ALTER TABLE schedules_new RENAME TO schedules;

CREATE INDEX idx_schedules_script ON schedules(script_id);
CREATE INDEX idx_schedules_due ON schedules(enabled, next_run_at);
CREATE UNIQUE INDEX idx_schedules_webhook_token_hash
    ON schedules(webhook_token_hash)
    WHERE webhook_token_hash IS NOT NULL;