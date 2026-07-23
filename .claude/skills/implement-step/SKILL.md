---
name: implement-step
description: Implement one already-approved FlowForge milestone step efficiently. Invoke explicitly when the user says "implement step X" or provides an approved implementation spec.
disable-model-invocation: true
---

# implement-step

Implement exactly ONE already-approved milestone step. Nothing more.

## Workflow

1. **Identify the exact step.** Confirm the step name and scope from the user's message or the linked spec. If ambiguous, ask one short clarifying question and stop.
2. **Inspect only relevant files.** Read the specific modules and tests named in the spec. Do not scan the wider repo.
3. **Check `git status`.** Note any uncommitted changes.
4. **Brief plan.** One short paragraph: module(s) to add/modify, public types/functions, tests to add, any new settings.
5. **Frozen-architecture guard.** If the step requires changing frozen architecture (per `docs/ADR.md`), stop and report before writing code.
6. **Implement only the requested scope.** No refactors, no extra features, no future-milestone work.
7. **Add or update tests.** Match the existing style in `backend/tests/`.
8. **Run relevant quality gates** from `backend/`:
