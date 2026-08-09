# Operations

## Backup

Stop writes, then copy `/data/scriptdeck.db` and `/storage`. For online SQLite backups, use `sqlite3 /data/scriptdeck.db ".backup /backup/scriptdeck.db"`.

## Restore

Stop ScriptDeck, restore both paths with ownership matching container UID/GID 10001, then restart and check `/health`.

## Upgrade

Back up first, pull the desired immutable version tag, and recreate the container. Database migrations run at startup. Do not downgrade a migrated database without restoring its matching backup.

## Import from bugy/script-server

Export `scripts.json`, `schedules.json`, and referenced script files into one directory, then run:

```bash
scriptdeck import bugy-script-server /path/to/export
```

The importer creates records and copies source files. It never executes imported scripts; unsupported rows are logged and skipped.
