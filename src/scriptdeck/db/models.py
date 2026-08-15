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