CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES schedules(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    exit_code INTEGER,
    status TEXT NOT NULL CHECK (status IN (
        'running', 'success', 'failure', 'error', 'cancelled'
    )),
    retry_group TEXT
);
CREATE INDEX idx_runs_script ON runs(script_id);
CREATE INDEX idx_runs_started ON runs(started_at DESC);