-- v2.0: tighten CHECK constraint to exclude 'bash' (BREAKING change from v1).
-- API already rejects 'bash' on create; this enforces it at the DB level for
-- any pre-existing rows from v1 imports.
-- SQLite cannot ALTER a CHECK constraint in place, so we rebuild the table.

PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

CREATE TABLE scripts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL CHECK (language IN ('python', 'node')),
    source_path TEXT NOT NULL,
    requirements_path TEXT,
    interpreter_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);
CREATE INDEX idx_scripts_name_new ON scripts_new(name);

INSERT INTO scripts_new (id, name, language, source_path, requirements_path,
                         interpreter_path, created_at, updated_at, description)
SELECT id, name, language, source_path, requirements_path, interpreter_path,
       created_at, updated_at, description
FROM scripts
WHERE language != 'bash';

DROP TABLE scripts;
ALTER TABLE scripts_new RENAME TO scripts;
CREATE INDEX idx_scripts_name ON scripts(name);

COMMIT;
PRAGMA foreign_keys=ON;