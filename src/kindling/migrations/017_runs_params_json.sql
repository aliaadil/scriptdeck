-- Migration 017: record the params used on each manual run.
--
-- Manual runs started from /api/kindling/scripts/{id}/run can now accept
-- a params_json object, exported as KINDLING_PARAM_<KEY>=<value> env vars
-- AND mapped to language-appropriate argv (positional for python/bash,
-- --key value for node). Persist the JSON so future run-detail UI can
-- show what params were used and audits can correlate.
--
-- Nullable on purpose: schedule/webhook runs that don't go through the
-- new manual endpoint have no params_json; existing rows are pre-feature.

ALTER TABLE runs ADD COLUMN params_json TEXT;
