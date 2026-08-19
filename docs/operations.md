# Operations

## Backup

Stop writes, then copy `/data/kindling.db` and `/storage`. For online SQLite backups, use `sqlite3 /data/kindling.db ".backup /backup/kindling.db"`.

## Restore

Stop Kindling, restore both paths with ownership matching container UID/GID 10001, then restart and check `/health`.

## Upgrade

Back up first, pull the desired immutable version tag, and recreate the container. Database migrations run at startup. Do not downgrade a migrated database without restoring its matching backup.

## Import from bugy/script-server

Export `scripts.json`, `schedules.json`, and referenced script files into one directory, then run:

```bash
kindling import bugy-script-server /path/to/export
```

The importer creates records and copies source files. It never executes imported scripts; unsupported rows are logged and skipped.
