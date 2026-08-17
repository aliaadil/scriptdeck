-- Backfill existing runs.started_at: convert naive 'YYYY-MM-DD HH:MM:SS' (SQLite
-- datetime('now') default) to tz-aware ISO-8601 UTC. Rows already containing
-- 'T' or '+' or 'Z' (v2 installs, app-side writes) are detected and left alone.
UPDATE runs
SET started_at = substr(started_at, 1, 10) || 'T' || substr(started_at, 12) || '+00:00'
WHERE started_at IS NOT NULL
  AND instr(started_at, 'T') = 0
  AND instr(started_at, '+') = 0
  AND instr(started_at, 'Z') = 0;
