# FlowForge AI

**AI-Powered Requirements Intelligence & Engineering Decision Platform.**

FlowForge ingests a requirements document and a Python repository and produces an
explainable **Requirement Traceability Matrix** — for every requirement: whether it
is implemented, whether it is tested, the supporting evidence, a confidence band, and
engineering-risk / business-impact insights to support engineering decisions.

> **Status:** In development · Milestone 0 (scaffolding).
> The architecture is **frozen** — see [`docs/ADR.md`](docs/ADR.md). This README
> grows as milestones land.

## Tech stack

- **Backend:** FastAPI · Python 3.12 · SQLAlchemy · PostgreSQL + pgvector
- **AI:** Claude (reasoning engine) · BGE-M3 (local embeddings)
- **Frontend:** Next.js · React · TypeScript · Tailwind
- **Tooling:** uv · ruff · mypy · pytest · Docker · GitHub Actions

## Repository layout

```
flowforge/
├── backend/     # FastAPI service (api, services, adapters, domain) — from M0.2
├── frontend/    # Next.js app — from M0.6
├── docs/        # Frozen architecture contract (ADR + System Design)
├── .env.example # Config template — copy to .env (never commit .env)
└── .gitignore
```

## Documentation

- [`docs/ADR.md`](docs/ADR.md) — Architecture Decision Records (frozen contract).
- [`docs/SystemDesign.md`](docs/SystemDesign.md) — Complete system design blueprint.

## Getting started

Local setup instructions arrive with the backend app (M0.2) and Docker (M0.4).
Right now this repository is an intentionally empty, runnable skeleton.

## Milestone 0 progress

- [x] 0.1 — Repository skeleton
- [ ] 0.2 — Backend app + tooling (uv, ruff, mypy, pytest, `/health`)
- [ ] 0.3 — Config + structured logging
- [ ] 0.4 — Containerization + DB connectivity (`/health/ready`)
- [ ] 0.5 — CI pipeline (GitHub Actions)
- [ ] 0.6 — Frontend stub
