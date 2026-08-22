from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import registry

mapper_registry = registry()

users = Table(
    "users",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_login_at", Text, nullable=True),
    Column("timezone", String, nullable=False, default="UTC"),
    CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="users_role_check"),
)

invites = Table(
    "invites",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String, nullable=False),
    Column("token", String, nullable=False, unique=True),
    Column("role", String, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("used_at", Text, nullable=True),
    Index("idx_invites_token", "token"),
)

script_envs = Table(
    "script_envs",
    mapper_registry.metadata,
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("ciphertext", String, nullable=False),  # base64 BLOB stored as TEXT
    Column("nonce", String, nullable=False),
    Column("updated_at", Text, nullable=False),
)

script_deps = Table(
    "script_deps",
    mapper_registry.metadata,
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("deps_json", Text, nullable=False),
    Column("source", String, nullable=False),
    Column("updated_at", Text, nullable=False),
)

audit_log = Table(
    "audit_log",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("action", String, nullable=False),
    Column("resource_type", String, nullable=False),
    Column("resource_id", Integer),
    Column("at", Text, nullable=False),
    Column("meta_json", Text, nullable=False),
)

scripts = Table(
    "scripts",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False, unique=True),
    Column("language", String, nullable=False),
    Column("source_path", String, nullable=False),
    Column("requirements_path", String),
    Column("interpreter_path", String),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("description", Text),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE")),
    Column("entrypoint", String, nullable=False, server_default="main.py"),
    CheckConstraint("language IN ('python', 'node', 'bash')", name="scripts_language_check"),
    Index("idx_scripts_name", "name"),
    Index("idx_scripts_user", "user_id", "id"),
)

schedules = Table(
    "schedules",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String, nullable=False),
    Column("expression", String),  # nullable: webhook rows have no expression
    Column("enabled", Integer, nullable=False, default=1),
    Column("next_run_at", String),  # nullable: webhook rows have no next_run_at
    Column("retry_max", Integer, nullable=False, default=0),
    Column("retry_backoff", Integer, nullable=False, default=0),
    Column("last_status", String),
    Column("last_error", Text),
    Column("timezone", String),
    Column("blackout_dates", Text),
    Column("include_days", Text),
    Column("overlap_policy", String, nullable=False, default="skip"),
    Column("queue_max", Integer, nullable=False, default=10),
    Column("queue_dropped", Integer, nullable=False, default=0),
    # Migration 015: per-trigger params + webhook token hash. Both nullable;
    # webhook rows have next_run_at NULL and expression NULL.
    Column("params_json", Text),
    Column("webhook_token_hash", String),
    CheckConstraint(
        "kind IN ('cron', 'interval', 'webhook')",
        name="schedules_kind_check",
    ),
    Index("idx_schedules_script", "script_id"),
    Index("idx_schedules_due", "enabled", "next_run_at"),
)

runs = Table(
    "runs",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "schedule_id",
        Integer,
        ForeignKey("schedules.id", ondelete="SET NULL"),
    ),
    Column("started_at", String, nullable=False),
    Column("ended_at", String),
    Column("exit_code", Integer),
    Column("status", String, nullable=False),
    Column("retry_group", String),
    Column("attempt", Integer, nullable=False, default=0),
    # parent_run_id is reserved for a future multi-row retry-chain model.
    # The current implementation uses single-row attempt increment
    # (run.attempt = ...) per the spec's "Retry State Machine" section,
    # so this column is intentionally unused. Leave the FK in place so
    # a future migration can start populating it without a schema change.
    Column("parent_run_id", Integer, ForeignKey("runs.id", ondelete="SET NULL")),
    Column("next_attempt_at", String),
    Column("skip_reason", String),
    # Migration 016: how this run was triggered. 'manual' / 'cron' /
    # 'interval' / 'webhook'. The schedule_id FK alone can't tell webhook
    # runs apart from schedule runs (webhook rows reuse the schedules
    # table with schedule_id pointing at the webhook trigger row), so the
    # UI needs an explicit field. Nullable for rows written before this
    # migration.
    Column("trigger_kind", String),
    # Migration 017: params supplied to a manual run, stored as a JSON
    # string. Nullable — schedule/webhook runs and pre-feature manual
    # runs have no value.
    Column("params_json", Text),
    CheckConstraint(
        "status IN ('running', 'success', 'failure', 'error', 'cancelled', "
        "'skipped', 'pending', 'pending_retry')",
        name="runs_status_check",
    ),
    Index("idx_runs_script", "script_id"),
    Index("idx_runs_started", text("started_at DESC")),
    Index("idx_runs_script_started", "script_id", text("started_at DESC")),
    Index("idx_runs_status", "status"),
)
