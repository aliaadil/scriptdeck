# Kindling quickstart

Kindling stores scripts, schedules, and run metadata in SQLite and keeps script artifacts and logs on disk.

```bash
docker run --name kindling -p 8765:8765 \
  -e KINDLING_BASIC_AUTH='admin:$2b$12$replace_with_bcrypt_hash' \
  -v kindling-data:/data -v kindling-storage:/storage \
  ghcr.io/aliaadil/kindling:1.0.0
```

Open `http://localhost:8765`, authenticate, upload a script, and add a cron or interval schedule. Use `GET /health` for service health.
