-- Schedules v2: timezone, day filter, blackout dates, overlap policy.
-- Runs v2: attempt tracking, parent_run_id, skip_reason; widen status enum.

ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC';

ALTER TABLE schedules ADD COLUMN timezone TEXT;
ALTER TABLE schedules ADD COLUMN blackout_dates TEXT;
ALTER TABLE schedules ADD COLUMN include_days TEXT;
ALTER TABLE schedules ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'skip';
ALTER TABLE schedules ADD COLUMN queue_max INTEGER NOT NULL DEFAULT 10;
ALTER TABLE schedules ADD COLUMN queue_dropped INTEGER NOT NULL DEFAULT 0;

ALTER TABLE runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN parent_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE runs ADD COLUMN next_attempt_at DATETIME;
ALTER TABLE runs ADD COLUMN skip_reason TEXT;

-- Widen runs.status CHECK to include 'skipped', 'pending', 'pending_retry'.
-- SQLite can't ALTER a CHECK constraint; rebuild the table.
CREATE TABLE runs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES schedules(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    exit_code INTEGER,
    status TEXT NOT NULL,
    retry_group TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    parent_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    next_attempt_at DATETIME,
    skip_reason TEXT,
    CHECK (status IN (
        'running','success','failure','error','cancelled',
        'skipped','pending','pending_retry'
    ))
);
INSERT INTO runs_new (id, script_id, schedule_id, started_at, ended_at, exit_code, status, retry_group)
    SELECT id, script_id, schedule_id, started_at, ended_at, exit_code, status, retry_group FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;

CREATE INDEX idx_runs_next_attempt ON runs(next_attempt_at) WHERE status = 'pending_retry';
CREATE INDEX idx_runs_parent ON runs(parent_run_id);
CREATE INDEX idx_runs_group ON runs(retry_group);
