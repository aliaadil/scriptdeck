-- Rebuild runs to allow status='running' and status='cancelled'.
-- (Carried verbatim from v1's v5 migration.)
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    line_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_logs_run ON logs(run_id);