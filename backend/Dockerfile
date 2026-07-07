# syntax=docker/dockerfile:1

# ── Stage 1: builder — resolve and install deps into a venv ──────────
FROM python:3.12-slim AS builder

# uv: fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first (cached layer) using only the lock + manifest.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ── Stage 2: runtime — copy the venv + app, run as non-root ──────────
FROM python:3.12-slim AS runtime

# Create an unprivileged user to run the app.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Bring the prebuilt virtualenv from the builder; no build tools in runtime.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# App source last so code changes don't bust the dependency layer.
COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
