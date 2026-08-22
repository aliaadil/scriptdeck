-- Migration 016: record the trigger kind on each run.
--
-- webhook triggers share the schedules table (kind='webhook' rows), so
-- runs.schedule_id alone can't tell webhook runs apart from cron/interval
-- runs. The UI's "via schedule" badge was therefore wrong for webhook
-- runs. Add an explicit trigger_kind column on runs so the UI can label
-- the source truthfully.
--
-- 'manual' is reserved for runs started from /api/kindling/runs POST and
-- /api/kindling/scripts/{id}/run. Nullable on purpose — pre-migration rows
-- have no value and stay nullable forever rather than backfilling a
-- possibly-wrong guess.

ALTER TABLE runs ADD COLUMN trigger_kind TEXT;

-- Cheap partial index so the runs-list query (which filters by trigger_kind
-- in the UI badge) stays snappy as the table grows.
CREATE INDEX idx_runs_trigger_kind ON runs(trigger_kind)
    WHERE trigger_kind IS NOT NULL;