-- 015_triggers.sql
-- Issue #17: allow a single script to fire from multiple triggers.
--
-- Additive only — every existing schedule keeps running unchanged because
-- (a) schedules.params_json defaults to '{}' so the runner sees the same
-- env it did before, and (b) the new webhooks table is a separate object
-- that scripts opt into by creating one.
--
-- Schema changes
-- --------------
-- schedules.params_json TEXT NOT NULL DEFAULT '{}'
--   Per-trigger key/value bag. The runner exports each top-level key as
--   SCRIPTDECK_PARAM_<KEY> (value as string) plus a single
--   SCRIPTDECK_PARAMS_JSON blob for callers that want the whole map.
--   Default '{}' is non-null and valid JSON so existing rows are happy
--   and the runner never has to special-case NULL.
--
-- webhooks(id, script_id, secret_token, enabled, params_json,
--          description, created_at, last_fired_at, fire_count)
--   A webhook is the second trigger kind. secret_token is unique and
--   uses 32 bytes from secrets.token_urlsafe (~43 url-safe chars, ~190
--   bits of entropy). The token is the only credential at the public
--   /webhooks/<token> endpoint — no JWT, no Basic auth, just the URL.
--   fire_count + last_fired_at give the UI something cheap to show.

ALTER TABLE schedules ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    secret_token TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    params_json TEXT NOT NULL DEFAULT '{}',
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_fired_at TEXT,
    fire_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_webhooks_script ON webhooks(script_id);
-- Partial unique index keeps token lookups O(log n) while leaving the
-- disabled rows in place (we never delete on disable; the operator can
-- regenerate the token to invalidate the URL instead).
CREATE UNIQUE INDEX idx_webhooks_token ON webhooks(secret_token)
    WHERE enabled = 1;
