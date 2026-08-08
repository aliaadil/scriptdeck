# syntax=docker/dockerfile:1.7
#
# ScriptDeck image — single-host scheduled script runner.
#
# Build:  docker build -t scriptdeck:dev .
# Run:    docker run --rm -p 8765:8765 \
#             -v scriptdeck-data:/data -v scriptdeck-storage:/storage \
#             -e SCRIPTDECK_BASIC_AUTH=user:bcrypt-hash \
#             scriptdeck:dev
#
# Multi-stage build keeps the runtime image small (~120 MB) by not
# carrying pip / build tooling. Non-root `app` user; persistent
# volumes on /data (scriptdeck.db) and /storage (script artifacts + logs).
ARG PYTHON_VERSION=3.12

# ---- builder --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# OS deps: only what we need to compile any C extensions in the dep tree.
# Most pure-python deps don't need this, but `requests` has charset_normalizer
# and a couple of indirects. Keeps image lean without sacrificing reliability.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc \
 && rm -rf /var/lib/apt/lists/*

# Install the package into an isolated prefix we can copy across stages.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install --no-build-isolation .

# ---- runtime --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Create the non-root user the service runs as. UID 10001 matches the
# convention used by most Coolify / Portainer deployments.
RUN groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

# Copy the installed package + its dependencies from the builder.
COPY --from=builder /install /usr/local

# Persistent data roots.
RUN mkdir -p /data /storage \
 && chown -R app:app /data /storage

WORKDIR /app
USER app

# Defaults — operators override via -e / docker-compose env block.
ENV SCRIPTDECK_DB_PATH=/data/scriptdeck.db \
    SCRIPTDECK_STORAGE_DIR=/storage \
    SCRIPTDECK_HOST=0.0.0.0 \
    SCRIPTDECK_PORT=8765 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8765

# Health check hits /health (a 200 with {"status": "ok"}). start-period
# gives the SQLite migration runner a moment to initialise on first boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).status == 200 else 1)"

# Console-script entry point installed by pyproject.toml.
ENTRYPOINT ["scriptdeck"]
# No default CMD — `scriptdeck` boots the HTTP server with no args.
CMD []