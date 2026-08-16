-- NEW for v2.0. Adds users, invites, script_envs, script_deps, audit_log.
-- The four original tables are inherited from migrations 001-006.

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX idx_invites_token ON invites(token);

CREATE TABLE script_envs (
    script_id INTEGER PRIMARY KEY REFERENCES scripts(id) ON DELETE CASCADE,
    ciphertext BLOB NOT NULL,
    nonce BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE script_deps (
    script_id INTEGER PRIMARY KEY REFERENCES scripts(id) ON DELETE CASCADE,
    deps_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('auto', 'manual')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    meta_json TEXT NOT NULL DEFAULT '{}'
);