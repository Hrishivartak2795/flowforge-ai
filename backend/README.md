# FlowForge Backend

FastAPI service for FlowForge AI, built on a pragmatic layered architecture (ADR-015):

```
api/  →  services/  →  domain/
                └── adapters/  (LLM, embedder, vectorstore — swappable, mockable)
```

Dependencies point inward; the `domain/` layer depends on nothing.

## Quick start

### One-time setup

```bash
# Install uv (https://docs.astral.sh/uv/getting-started/installation/)
# Then from this directory:
uv sync
```

### Running locally

```bash
# Start the server with auto-reload
uv run uvicorn app.main:app --reload

# Then in another terminal, test it
curl http://127.0.0.1:8000/health
# → {"status":"ok"}

# View API docs
# Open http://127.0.0.1:8000/docs in your browser
```

### Tests & quality gates

```bash
uv run pytest                   # Run tests
uv run ruff check .             # Lint
uv run ruff format .            # Auto-format
uv run mypy app tests           # Type check (strict mode)

# Or all at once
uv run pytest && uv run ruff check . && uv run mypy app tests
```

## Configuration

Copy `.env.example` to `.env` (git-ignored) and fill in real values:

```bash
cp .env.example .env
```

The app reads configuration from environment variables (process env or `.env` file).

## Architecture

See [`../docs/SystemDesign.md`](../docs/SystemDesign.md) §7 for the full backend architecture and the planned folder structure as new layers (services, adapters, database) are added.

**Current structure** (M0.3):
- `app/api/routes/` — HTTP endpoints and Pydantic request/response contracts.
- `app/core/` — cross-cutting infra (config, logging, and later: database, error handling).
- `tests/` — pytest suite; mirrors `app/` structure.

Implementation begins in **Milestone 0.2**. Each milestone adds new packages and layers without changing the core composition pattern (factory + dependency injection).
