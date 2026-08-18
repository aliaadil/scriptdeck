-- 013_entrypoint.sql
-- Add entrypoint column to scripts and backfill defaults by language.
-- Idempotent: skip if the column already exists (e.g. developer re-running
-- migrations after a partial schema).

ALTER TABLE scripts ADD COLUMN entrypoint VARCHAR(500) NOT NULL DEFAULT 'main.py';

UPDATE scripts SET entrypoint = 'main.py' WHERE language = 'python' AND (entrypoint IS NULL OR entrypoint = 'main.py');
UPDATE scripts SET entrypoint = 'main.js' WHERE language = 'node' AND (entrypoint IS NULL OR entrypoint = 'main.py');
UPDATE scripts SET entrypoint = 'main.sh' WHERE language = 'bash' AND (entrypoint IS NULL OR entrypoint = 'main.py');
