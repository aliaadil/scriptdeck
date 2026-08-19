-- 014_bash_language.sql
-- Re-introduce 'bash' as a valid script language (reverses 009_no_bash.sql).
-- The multi-file script editor (Task 4 of feat/script-editor) supports bash:
--   * API: ScriptCreate.language is now `python|node|bash`.
--   * DB: relax the CHECK constraint on scripts.language.
-- Mirrors the rebuild approach used in 009_no_bash.sql because SQLite cannot
-- ALTER a CHECK constraint in place. The table layout doesn't otherwise change
-- (we keep the entrypoint column added in 013_entrypoint.sql).

PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

CREATE TABLE scripts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL CHECK (language IN ('python', 'node', 'bash')),
    source_path TEXT NOT NULL,
    requirements_path TEXT,
    interpreter_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    entrypoint VARCHAR(500) NOT NULL DEFAULT 'main.py'
);

INSERT INTO scripts_new (id, name, language, source_path, requirements_path,
                         interpreter_path, created_at, updated_at, description,
                         user_id, entrypoint)
SELECT id, name, language, source_path, requirements_path, interpreter_path,
       created_at, updated_at, description, user_id, entrypoint
FROM scripts;

DROP TABLE scripts;
ALTER TABLE scripts_new RENAME TO scripts;
CREATE INDEX idx_scripts_name ON scripts(name);
CREATE INDEX idx_scripts_user ON scripts(user_id, id);

COMMIT;
PRAGMA foreign_keys=ON;
