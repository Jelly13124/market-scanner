# syntax=docker/dockerfile:1
# Multi-stage image for Fly.io: one image = built Vite SPA + python backend.
#   stage `frontend`: node builds the SPA -> /fe/dist
#   stage `backend` : python installs deps, copies the app + the built dist,
#                     entrypoint runs alembic migrations then uvicorn.

# --- frontend build ---
FROM node:20-slim AS frontend
WORKDIR /fe
# Copy manifest + lockfile first so `npm ci` layer caches on dep changes only.
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
# VITE_API_URL is baked into the bundle at build time. Empty default => the SPA
# calls the same origin it is served from (single-origin deploy), which is what
# we want on Fly. Override via --build-arg for a split-origin setup.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build         # tsc && vite build -> /fe/dist

# --- backend ---
FROM python:3.13-slim AS backend
WORKDIR /app

# build-essential: some wheels (psycopg2-binary deps, etc.) compile from source.
# curl: lets Fly/health tooling probe the container if needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install python deps via Poetry (this is a Poetry project — pyproject.toml has
# [tool.poetry]). We install into the system interpreter (no venv) so uvicorn /
# alembic resolve on PATH. `--only main` skips dev tools (pytest/black/flake8).
# `--no-root` skips installing the project itself as a package here — we COPY the
# source in directly and run via PYTHONPATH, so there's nothing to build/install.
COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir "poetry==1.8.5" \
    && poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# App code (respects .dockerignore).
COPY . .

# Built frontend -> where FRONTEND_DIST points (default app/frontend/dist; prod
# sets FRONTEND_DIST=/app/app/frontend/dist which resolves to this same path).
COPY --from=frontend /fe/dist ./app/frontend/dist

# Normalize the entrypoint's line endings. This repo has core.autocrlf=true and
# no .gitattributes, so a Windows checkout can give the .sh file CRLF, which the
# Linux `bash` would reject with "bad interpreter". Strip CRs to be build-safe.
RUN sed -i 's/\r$//' docker/entrypoint.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["bash", "docker/entrypoint.sh"]
