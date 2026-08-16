-- Adds user_id to scripts for per-user isolation. Backfills from the first
-- admin user. Existing single-user installs end up with all scripts owned
-- by admin. Multi-user installs must run `scriptdeck migrate-users` before
-- flipping SCRIPTDECK_SANDBOX_ENABLED=true.

ALTER TABLE scripts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

UPDATE scripts SET user_id = (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1)
WHERE user_id IS NULL;

CREATE INDEX idx_scripts_user ON scripts(user_id, id);