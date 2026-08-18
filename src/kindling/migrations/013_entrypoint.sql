-- 013_entrypoint.sql
-- Add entrypoint column to scripts and backfill defaults by language.

ALTER TABLE scripts ADD COLUMN entrypoint VARCHAR(500) NOT NULL DEFAULT 'main.py';

UPDATE scripts SET entrypoint = 'main.py' WHERE language = 'python';
UPDATE scripts SET entrypoint = 'main.js' WHERE language = 'node';
UPDATE scripts SET entrypoint = 'main.sh' WHERE language = 'bash';
