# Install

## Docker

Build locally with `docker build -t kindling:1.0.0 .`, or pull `ghcr.io/aliaadil/kindling:1.0.0`. Persist `/data` and `/storage`; the container listens on port 8765.

## Coolify

Create a Docker Compose resource from the repo's `docker-compose.yml`. Set `KINDLING_BASIC_AUTH` to `username:bcrypt_hash`, map port 8765, and retain both named volumes.

## Manual

```bash
python -m venv .venv
. .venv/bin/activate
pip install .[auth]
KINDLING_DB_PATH=/var/lib/kindling/kindling.db \
KINDLING_STORAGE_DIR=/var/lib/kindling/storage kindling
```

A hardened systemd unit and environment example live in `packaging/systemd/`.
