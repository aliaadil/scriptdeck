"""Copy a v1 Kindling SQLite DB + storage into a fresh v2 DB.

v1 schema: scripts, schedules, runs, logs.
v2 inherits all four tables via migrations 001-006 (applied on the fresh
v2 DB before this runs). Then we copy rows directly. No transformation
required because v2 didn't change the four original tables.

v2 also has a ``script_envs`` table holding AES-GCM encrypted per-script
.env blobs. v1 used a different AES key (the same KINDLING_ENV_ENCRYPTION_KEY
the v1 process booted with), so v2 cannot decrypt v1 ciphertexts without
that key. Operators MUST pass --v1-env-encryption-key; otherwise the script
names with env blobs are listed and the migration refuses to run, because
silently dropping encrypted env data would leave scripts in a state where
they run with empty environments.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite

from kindling.services.env_service import EnvService


async def _copy_table(src: aiosqlite.Connection, dst: aiosqlite.Connection, table: str) -> int:
    cur = await src.execute(f"SELECT * FROM {table}")
    rows = await cur.fetchall()
    cols = [c[0] for c in cur.description]
    if not rows:
        return 0
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    await dst.executemany(
        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
        rows,
    )
    await dst.commit()
    return len(rows)


async def _list_scripts_with_env_blobs(
    src: aiosqlite.Connection,
) -> list[tuple[int, str]]:
    """Return [(script_id, script_name)] for every v1 script with an env row.

    Used to warn the operator that env blobs exist and would be dropped if no
    --v1-env-encryption-key was provided.
    """
    cur = await src.execute(
        "SELECT e.script_id, s.name FROM script_envs e "
        "JOIN scripts s ON s.id = e.script_id"
    )
    return [(row[0], row[1]) for row in await cur.fetchall()]


async def _migrate_env_blobs(
    src: aiosqlite.Connection,
    dst: aiosqlite.Connection,
    v1_key_b64: str,
    v2_key_b64: str,
) -> int:
    """Decrypt every v1 script_envs row under v1_key and re-encrypt under
    v2_key, then write into the v2 script_envs table."""
    v1 = EnvService(v1_key_b64)
    v2 = EnvService(v2_key_b64)
    cur = await src.execute("SELECT script_id, ciphertext, nonce FROM script_envs")
    rows = await cur.fetchall()
    if not rows:
        return 0
    migrated = 0
    for script_id, ct_b64, nonce_b64 in rows:
        try:
            plaintext = v1.decrypt(ct_b64, nonce_b64)
        except Exception as exc:
            # Don't abort the whole migration on a single bad row — log and
            # skip. The operator can re-run after fixing the v1 key.
            print(
                f"  warn: script_id={script_id} env blob failed to decrypt "
                f"under v1 key: {exc!r} (skipping)"
            )
            continue
        new_ct_b64, new_nonce_b64 = v2.encrypt(plaintext)
        await dst.execute(
            "INSERT OR REPLACE INTO script_envs (script_id, ciphertext, nonce, updated_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (script_id, new_ct_b64, new_nonce_b64),
        )
        migrated += 1
    await dst.commit()
    return migrated


async def run_async(
    v1_db: str,
    v1_storage: str,
    v2_db: str,
    v2_storage: str,
    v1_env_encryption_key: str | None = None,
    v2_env_encryption_key: str | None = None,
) -> int:
    # Caller must have already created v2 DB and applied migrations.
    v1_db_p = Path(v1_db)
    if not v1_db_p.exists():
        raise FileNotFoundError(v1_db)
    Path(v2_storage).mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(v1_db)) as src, aiosqlite.connect(v2_db) as dst:
        # Inspect env blobs BEFORE copying any rows. If any exist and the
        # caller didn't supply --v1-env-encryption-key, refuse to proceed
        # rather than silently drop them.
        scripts_with_envs = await _list_scripts_with_env_blobs(src)
        if scripts_with_envs and not v1_env_encryption_key:
            names = ", ".join(f"{sid}:{name}" for sid, name in scripts_with_envs)
            raise RuntimeError(
                f"v1 DB has {len(scripts_with_envs)} encrypted .env blobs "
                f"({names}). Re-run with --v1-env-encryption-key=<base64> to "
                f"migrate them, or accept they will be dropped (scripts will "
                f"run with empty environments until reconfigured)."
            )

        total = 0
        for table in ("scripts", "schedules", "runs", "logs"):
            total += await _copy_table(src, dst, table)

        # Migrate encrypted env blobs when keys were supplied.
        if scripts_with_envs and v1_env_encryption_key and v2_env_encryption_key:
            env_total = await _migrate_env_blobs(
                src, dst, v1_env_encryption_key, v2_env_encryption_key
            )
            print(f"migrated {env_total} encrypted .env blobs (re-keyed)")
            total += env_total
        elif scripts_with_envs and v1_env_encryption_key and not v2_env_encryption_key:
            print(
                "warn: --v1-env-encryption-key supplied without --v2-env-encryption-key; "
                "env blobs will be copied under the v1 key. The v2 process must "
                "boot with KINDLING_ENV_ENCRYPTION_KEY=<v1-key> until the next "
                "explicit re-key."
            )
            env_total = await _migrate_env_blobs(
                src, dst, v1_env_encryption_key, v1_env_encryption_key
            )
            total += env_total

    # Copy storage scripts/* if present.
    src_storage = Path(v1_storage) / "scripts"
    if src_storage.exists():
        dest_storage = Path(v2_storage) / "scripts"
        dest_storage.mkdir(parents=True, exist_ok=True)
        for entry in src_storage.iterdir():
            target = dest_storage / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
    return total


def run(
    v1_db: str,
    v1_storage: str,
    v2_db: str,
    v2_storage: str,
    v1_env_encryption_key: str | None = None,
    v2_env_encryption_key: str | None = None,
) -> int:
    import asyncio
    n = asyncio.run(
        run_async(
            v1_db, v1_storage, v2_db, v2_storage,
            v1_env_encryption_key=v1_env_encryption_key,
            v2_env_encryption_key=v2_env_encryption_key,
        )
    )
    print(f"migrated {n} rows from v1 to v2")
    return 0
