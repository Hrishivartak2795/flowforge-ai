# RESUME — FlowForge AI

> **Purpose:** a fast handoff note so a fresh chat session (or future-you) can pick up
> instantly. This is the "where am I?" file. Update the **Status** and **Next** sections
> after every milestone. Deeper context lives in `docs/DeveloperJournal.md`.
>
> **Last updated:** end of M0.4 (code committed; not yet verified locally).

---

## What this project is

**FlowForge AI** — an AI-Powered Requirements Intelligence & Engineering Decision Platform.
It ingests a **requirements document** + a **Python repository** and produces an explainable
**Requirement Traceability Matrix**: for every requirement — implemented / partial / missing,
tested or not, with cited code as evidence, a confidence band, and engineering-risk /
business-impact insights. Claude is the only reasoning engine; deterministic code does
everything else.

- **Repo:** <ADD YOUR GITHUB URL HERE>
- **Architecture status:** **FROZEN** (see `docs/ADR.md`). Do not re-open decisions unless
  implementation reveals a real, demonstrated problem.

## Documents to read (in order)

1. `docs/DeveloperJournal.md` — full current state, file-by-file, concepts learned. **Read first.**
2. `docs/ADR.md` — the frozen architectural contract (decisions + rejected alternatives).
3. `docs/SystemDesign.md` — full blueprint (schema, API, folder structures, roadmap).

## Current status

Completed and committed to GitHub:

- [x] **M0.1** — Repository skeleton
- [x] **M0.2** — Backend skeleton & tooling (FastAPI, uv, ruff, mypy, pytest, `/health`)
- [x] **M0.3** — Configuration (pydantic-settings) + structured JSON logging
- [x] **M0.4** — Docker + PostgreSQL 16 + pgvector + async SQLAlchemy + `/health/ready`
      ⚠️ **Code written & committed, but NOT yet verified locally** (Docker was just installed).

## Immediate next action

1. Verify M0.4 locally:
   ```bash
   docker compose up --build
   curl http://127.0.0.1:8000/health         # 200 {"status":"ok"}
   curl http://127.0.0.1:8000/health/ready    # 200 {"status":"ok","database":"up"}
   docker compose exec db psql -U flowforge -d flowforge \
     -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
   ```
2. Once green, commit confirmation and proceed to **M0.5 — CI pipeline (GitHub Actions)**.

## Roadmap position

**Milestone 0 (infrastructure):** 0.1 ✅ · 0.2 ✅ · 0.3 ✅ · 0.4 ✅(unverified) · 0.5 ⬜ CI · 0.6 ⬜ frontend stub
**Then:** M1 schema + Alembic migrations (incl. `CREATE EXTENSION vector`) → M2 upload → M3 AST parsing →
M4 embeddings/pgvector/retrieval → M5 Claude → M6–M8 traceability + reports → M9 async → M10 frontend →
M11 eval harness → M12 optimization → M13 deploy.

## How to work with me (paste-ready role prompt for a new chat)

> Act as my **Senior Software Engineer and Technical Lead** for FlowForge AI. The architecture
> is **frozen** (see `docs/ADR.md`); keep everything aligned with the ADR and System Design and
> do not re-open decisions unless implementation reveals a real problem.
>
> I've learned the fundamentals — **optimize for speed** on infrastructure milestones (I know
> FastAPI, uv, pytest, Docker, DI, app factory, composition root). **Slow down and explain deeply**
> for the AI milestones: AST parsing, embeddings, pgvector retrieval, Claude integration, prompt
> engineering, traceability engine, executive insights.
>
> Per milestone: short objective → note only decisions affecting future architecture → generate
> the files → say where each belongs → manual testing steps → **wait for my confirmation** before
> the next milestone. Use `uv`; keep ruff/mypy/pytest green; strict typing throughout. I'm on
> **Windows / PowerShell**. After each milestone, give me the **full updated** `DeveloperJournal.md`
> to replace mine.

## Environment / setup state

- ✅ `uv`, `git`, Docker Desktop installed (Windows).
- ⬜ **Node.js** — install at M0.6/M10 (frontend). Not needed before then.
- ⬜ **Anthropic API key** — needed at M5. Get from https://console.anthropic.com, put in
  `backend/.env` as `ANTHROPIC_API_KEY=...` (already wired into Settings; git-ignored).
- BGE-M3 embedding model (M4) auto-downloads (~2 GB) via `sentence-transformers`; no manual install.

## Recommended model

Use **Opus** (most capable) for this project — architecture-aware code, multi-file debugging,
and the AI-pipeline work. Drop to Sonnet for routine edits if you hit limits, switch back to
Opus for design/complex code.

## Conventions

- Commits: Conventional Commits (`feat(backend): … (M0.x)`).
- Every milestone leaves the app runnable; walking-skeleton approach.
- Quality gates before every commit: `uv run ruff check . && uv run mypy app tests && uv run pytest`.
