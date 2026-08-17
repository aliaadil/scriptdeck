# Stage 1: frontend build
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Copy the source tree BEFORE `uv sync` so the editable install detects
# the package's modules when generating the lockfile-derived build.
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist ./src/kindling/dashboard_static/
EXPOSE 8765
# `uv sync` creates a project-local venv at /app/.venv. Make its bin
# directory available on PATH so the `kindling` console script installed
# by pyproject.toml is discoverable by the CMD below.
ENV PATH="/app/.venv/bin:$PATH" \
    KINDLING_HOST=0.0.0.0 \
    KINDLING_PORT=8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/kindling/health', timeout=3).status == 200 else 1)"
CMD ["kindling", "serve"]
