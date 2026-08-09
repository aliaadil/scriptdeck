# ScriptDeck quickstart

ScriptDeck stores scripts, schedules, and run metadata in SQLite and keeps script artifacts and logs on disk.

```bash
docker run --name scriptdeck -p 8765:8765 \
  -e SCRIPTDECK_BASIC_AUTH='admin:$2b$12$replace_with_bcrypt_hash' \
  -v scriptdeck-data:/data -v scriptdeck-storage:/storage \
  ghcr.io/aliaadil/scriptdeck:1.0.0
```

Open `http://localhost:8765`, authenticate, upload a script, and add a cron or interval schedule. Use `GET /health` for service health.
