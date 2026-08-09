# Install

## Docker

Build locally with `docker build -t scriptdeck:1.0.0 .`, or pull `ghcr.io/aliaadil/scriptdeck:1.0.0`. Persist `/data` and `/storage`; the container listens on port 8765.

## Coolify

Create a Docker Compose resource from `coolify/docker-compose.yml`. Set `SCRIPTDECK_BASIC_AUTH` to `username:bcrypt_hash`, map port 8765, and retain both named volumes.

## Manual

```bash
python -m venv .venv
. .venv/bin/activate
pip install .[auth]
SCRIPTDECK_DB_PATH=/var/lib/scriptdeck/scriptdeck.db \
SCRIPTDECK_STORAGE_DIR=/var/lib/scriptdeck/storage scriptdeck
```

A hardened systemd unit and environment example live in `packaging/systemd/`.
