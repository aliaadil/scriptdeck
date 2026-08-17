"""CLI entry: `kindling` or `python -m kindling`."""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="kindling")
    sub = parser.add_subparsers(dest="cmd", required=False)
    sub.add_parser("serve", help="Run the API server (default)")
    sub.add_parser("doctor", help="Validate config and DB")

    mig = sub.add_parser("migrate-from-v1", help="Copy v1 DB rows into a fresh v2 DB")
    mig.add_argument("--v1-db-path", required=True)
    mig.add_argument("--v1-storage-path", required=True)
    mig.add_argument(
        "--v2-db-path",
        default="./data/kindling.db",
        help="Path to the v2 SQLite DB (default: ./data/kindling.db)",
    )
    mig.add_argument(
        "--v2-storage-path",
        default="./storage",
        help="Path to the v2 storage directory (default: ./storage)",
    )
    mig.add_argument(
        "--v1-env-encryption-key",
        default=None,
        help=(
            "Base64-encoded AES-GCM key the v1 process booted with. Required "
            "if the v1 DB contains any script_envs rows; otherwise migration "
            "refuses to proceed."
        ),
    )
    mig.add_argument(
        "--v2-env-encryption-key",
        default=None,
        help=(
            "Base64-encoded AES-GCM key the v2 process will boot with. When "
            "supplied, env blobs are re-encrypted under this key during "
            "migration. Defaults to --v1-env-encryption-key when omitted."
        ),
    )

    mu = sub.add_parser("migrate-users", help="Move flat storage into per-user subtrees")
    mu.add_argument("--storage-dir", required=True)
    mu.add_argument("--db-path", required=True)
    mu.add_argument("--apply", action="store_true", help="Actually move files (default dry-run)")

    bak = sub.add_parser("backup", help="Tar db + storage")
    bak.add_argument("--output", required=True)

    res = sub.add_parser("restore", help="Restore tar backup")
    res.add_argument("--input", required=True)

    args = parser.parse_args()
    if args.cmd in (None, "serve"):
        from kindling.app import run
        run()
        return 0
    if args.cmd == "doctor":
        from kindling.cli_commands.doctor import run as doctor_run
        return doctor_run()
    if args.cmd == "migrate-from-v1":
        from kindling.cli_commands.migrate import run as mig_run
        return mig_run(
            v1_db=args.v1_db_path, v1_storage=args.v1_storage_path,
            v2_db=args.v2_db_path, v2_storage=args.v2_storage_path,
            v1_env_encryption_key=args.v1_env_encryption_key,
            v2_env_encryption_key=args.v2_env_encryption_key,
        )
    if args.cmd == "migrate-users":
        from kindling.cli_commands.migrate_users import migrate_users_run
        return migrate_users_run(
            storage_dir=args.storage_dir,
            db_path=args.db_path,
            dry_run=not args.apply,
        )
    if args.cmd == "backup":
        from kindling.cli_commands.backup import run as bak_run
        return bak_run(output=args.output)
    if args.cmd == "restore":
        from kindling.cli_commands.backup import restore as res_run
        return res_run(input=args.input)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
