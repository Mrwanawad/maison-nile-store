# syntax=docker/dockerfile:1

# --- 1. Front-end assets (Tailwind CSS + vendored JS). Node exists only here. ---
FROM node:22-slim AS assets
WORKDIR /build
COPY src/frontend src/frontend
COPY src/backend/app/views src/backend/app/views
WORKDIR /build/src/frontend
RUN npm ci --no-audit --no-fund && npm run build

# --- 2. Python dependencies ---------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONPATH=/srv/src/backend \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./

# --- dev target (docker compose): includes dev tools, code is bind-mounted ----
FROM base AS dev
RUN uv sync --frozen --no-install-project
COPY . .
COPY --from=assets /build/src/frontend/static src/frontend/static

# --- 3. Production runtime ------------------------------------------------------
FROM base AS runtime
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY src/backend src/backend
COPY --from=assets /build/src/frontend/static src/frontend/static
RUN useradd --create-home --uid 10001 appuser && mkdir -p media && chown appuser media
USER appuser
EXPOSE 8000
# Render sets $PORT. Migrations and the bootstrap (demo seed / first admin) run on start (idempotent).
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
