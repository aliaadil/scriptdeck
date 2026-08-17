CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('cron', 'interval')),
    expression TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT NOT NULL,
    retry_max INTEGER NOT NULL DEFAULT 0,
    retry_backoff INTEGER NOT NULL DEFAULT 0,
    last_status TEXT
);
CREATE INDEX idx_schedules_script ON schedules(script_id);