# Claude Code Instructions — FlowForge AI

Planning, architecture, and prompt design happen in a separate Claude Pro chat.
Your role here is **focused implementation** of already-approved milestone steps.

## Project Context (load only when needed)

- `docs/CLAUDE_HANDOFF.md` — current project state, milestone status, next task.
- `docs/ADR.md` — frozen architecture decisions.
- `docs/SystemDesign.md` — detailed system design.

Do not preload these. Read them only when the current task genuinely requires it.

## Permanent Rules

- Inspect only files relevant to the current task.
- Do not perform repository-wide exploration unless necessary.
- Do not reread all documentation for routine implementation.
- Preserve frozen architecture. If a task requires changing it, **stop and report**.
- Implement only the requested milestone step. Never implement future milestones early.
- Prefer deterministic logic before LLM reasoning.
- Never execute untrusted repository code.
- Never expose or commit secrets. Update `.env.example` (names only) when adding settings.
- Maintain Windows dev + Linux deploy compatibility (`pathlib.Path`, no POSIX-only APIs on the critical path).
- Maintain strict typing. All new code passes `mypy --strict`.
- Follow existing dependency-injection patterns (e.g. `get_db_session`).
- Use Alembic exclusively for schema changes. Applied migrations are immutable.
- Do not commit or push unless explicitly requested.
- Keep responses and implementation reports concise.

## Backend Quality Gates

Run from `backend/`:
