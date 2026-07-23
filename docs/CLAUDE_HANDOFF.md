# FlowForge AI — Engineering Handoff for Claude Code

> **Audience:** Claude Code (development assistant). This document is optimized for machine execution, not human onboarding. Human-facing narrative lives in `docs/DeveloperJournal.md` and `progress_report.md`.
>
> **Purpose:** hand off engineering continuity of FlowForge AI without loss of context. Read this first, then the four docs listed at the end.

---

## 1. Project Mission

FlowForge AI ingests a **software requirements document** and a **Python source repository** and produces an **explainable Requirement Traceability Matrix**: for every requirement, whether it is implemented (implemented / partial / missing), whether it is tested, the exact **cited code as evidence**, a confidence band derived from exposed signals, and per-requirement engineering-risk / business-impact scores.

The reasoning surface is a **seven-stage per-requirement pipeline**: Understand → Requirement Intelligence → Engineering Expectations → Traceability (flagship) → Engineering Risk → Business Impact → Executive Insights.

**MVP scope:** Python repositories only; single-user; no auth. Six-dimension business impact; five-dimension Requirement Intelligence Score; deterministic engineering risk; executive rollup with one narrative call; evaluation harness measuring the flagship (retrieval recall@k, verdict precision/recall, confidence separation). Compliance/audit is explicitly out of scope.

---

## 2. Current Project State

### Completed

- **M0.1** Repository Skeleton — monorepo, `.gitignore`, `.env.example`, docs-as-code.
- **M0.2** Backend Skeleton — FastAPI, uv, `create_app()` factory, `/health`, mypy strict, ruff, pytest.
- **M0.3** Configuration & Structured Logging — `Settings` via pydantic-settings, JSON logging, `app/core/`.
- **M0.4** Docker + PostgreSQL + pgvector — async SQLAlchemy 2.x, `get_db_session` DI, `/health/ready`, multi-stage image, compose with healthcheck.
- **M0.5** CI/CD — GitHub Actions running ruff + mypy + pytest + Docker build on push/PR to `main`.
- **M0.6** Frontend Skeleton — Next.js 16 App Router + React 19 + TypeScript strict + Tailwind v4 placeholder. **Decoupled**: no API calls yet.
- **M1** Database Schema & Alembic — the 8 domain tables (`project`, `requirements_doc`, `requirement`, `code_unit`, `test_unit`, `analysis_run`, `trace_link`, `trace_evidence`), extensions (`vector`, `pg_trgm`) in migrations, `vector(1024)` + HNSW cosine index, `tsvector` + GIN, XOR CHECK on evidence, cascade FKs, enum CHECKs.
- **M2 Step 1** Safe ZIP Ingestion + `CheckoutDir` — bounded temp dir with deterministic cleanup, ZIP extractor with zip-slip defense, symlink rejection, size and file-count caps, pre-flight validation before any disk write.
- **M2 Step 2** GitHub Repository Cloner — URL allow-list validation (HTTPS + github.com only), no embedded credentials, shallow clone with timeout, error hierarchy mapping.

### Current Position

**M2 — Repository Intelligence Engine** (in progress).

### Next Implementation

**M2 Step 3 — Repository File Discovery.**

---

## 3. Frozen Architecture

The following decisions are **frozen**. Do not casually change them. Authoritative sources: `docs/ADR.md` and `docs/SystemDesign.md`. Cross-reference the ADR number when in doubt.

- **Reasoning boundary (ADR-008).** Claude reasons; deterministic code does everything else. Parsing, embedding, retrieval, confidence composition, risk composition, business impact composition, and executive aggregation are all deterministic. Claude is called only for: requirement analysis (batched, one call per doc), per-expectation traceability verdicts, and the executive narrative.
- **Python-only for MVP.** Repository analysis targets `.py` files. A `LanguageParser` protocol keeps the door open for Java/JS/Go later without schema change, but do not implement other languages in the MVP.
- **Python stdlib `ast`.** No third-party parser. `ast.parse` never executes user code (safe on untrusted input).
- **No whole-repository prompts.** Claude never sees the whole repo. Verdicts run over a **focused retrieved candidate set** produced by hybrid retrieval.
- **PostgreSQL + pgvector (ADR-006, ADR-014).** Single datastore. `code_unit.dense_embedding vector(1024)` + HNSW cosine. `tsvector` + GIN for lexical. Model-flexible payloads live in JSONB alongside the relational spine.
- **BGE-M3 embeddings.** Local, dense, 1024-dim. No external embedding API.
- **Hybrid retrieval.** Dense (pgvector) + lexical (Postgres FTS / trigram) combined via RRF. All SQL against the same DB.
- **FastAPI + async SQLAlchemy 2.x + psycopg3 (async).** Application-factory pattern; DB session as a DI dependency (`get_db_session`). Adapters follow the same DI shape.
- **Alembic.** The **only** way schema and extensions are created. Applied migrations are immutable — new changes are new migrations, never edits to old ones.
- **Next.js 16 (App Router) + TS strict + Tailwind v4.** Frontend talks only to the backend REST API. Holds no secrets. Full UI arrives in M7.
- **Docker.** Multi-stage backend image; compose gates backend on DB healthcheck. Migrations ship inside the image (`docker compose exec backend alembic upgrade head`).
- **Evidence-backed traceability (ADR-011).** Every verdict cites `trace_evidence` rows pointing at exactly one `code_unit` or `test_unit` (XOR CHECK enforced at the DB).
- **Execution model (ADR-013).** Long analyses run as a FastAPI background task with a Postgres-backed status row. No Celery/Redis.
- **Confidence bands (ADR-010).** High/Medium/Low from a deterministic composite of four **exposed** signals — retrieval quality, evidence strength, implementation matches, reasoning confidence. Bands are stored with the signal breakdown; not discarded.
- **Advisory vs factual labeling (ADR-012, ADR-016).** LLM-judged dimensions are labeled advisory. Deterministic dimensions are labeled factual. Preserve this distinction in output shapes and UI copy.

If you believe a frozen decision is wrong, **stop and explain** before writing code. Do not silently rework the architecture.

---

## 4. Current Repository Architecture

Full detail is in `docs/DeveloperJournal.md` §4 and `docs/progress_report.md` §3. Do not re-derive; read those.

Key directories:

```
flowforge-ai/
├── .github/workflows/ci.yml
├── docker-compose.yml
├── frontend/                              # Next.js 16 skeleton (App Router)
└── backend/
    ├── Dockerfile · pyproject.toml · uv.lock · alembic.ini
    ├── migrations/                        # Alembic (M1)
    │   ├── env.py · script.py.mako
    │   └── versions/*_initial_schema.py
    └── app/
        ├── main.py                        # composition root: create_app()
        ├── core/                          # config.py · logging.py · db.py
        ├── domain/                        # M1: base.py · enums.py · models.py
        ├── api/routes/health.py           # /health + /health/ready
        └── services/
            ├── __init__.py
            └── ingestion/                 # M2 in progress
                ├── __init__.py
                ├── checkout.py            # CheckoutDir (step 1)
                ├── errors.py              # ingestion error hierarchy
                ├── zip_extractor.py       # safe ZIP extraction (step 1)
                └── git_cloner.py          # GitHub clone (step 2)
    └── tests/
        ├── conftest.py                    # fixtures + --run-network opt-in hook
        ├── test_health.py · test_readiness.py · test_config_and_logging.py
        ├── test_models.py                 # M1 schema shape
        └── services/
            ├── test_checkout.py
            ├── test_zip_extractor.py
            └── test_git_cloner.py         # network-marked integration test included
```

Read these documents before doing any work (in this order):

1. `docs/CLAUDE_HANDOFF.md` (this file).
2. `docs/ADR.md` — frozen architectural decisions.
3. `docs/SystemDesign.md` — full implementation blueprint (§6 data model, §8 frontend architecture).
4. `docs/DeveloperJournal.md` (or `developerjournal.md` if lowercase in the repo) — running detail per milestone; §3 has the M2 design freeze and per-step history.
5. Existing M2 ingestion code and tests: `backend/app/services/ingestion/*.py`, `backend/tests/services/test_*.py`.

---

## 5. Completed M2 Ingestion Architecture

Two input paths, one downstream abstraction. **Never bypass `CheckoutDir`** — every path that materializes a repository must produce one so downstream steps stay input-agnostic.

### ZIP path

```
ZIP upload (bytes on disk)
    ↓
extract_zip(zip_path, checkout, limits)
    ├── pre-flight validation (nothing hits disk until this passes):
    │     ├── reject empty / .. / absolute / backslash / drive-letter entry names
    │     ├── reject symlink entries (Unix mode 0o120000 in external_attr high bits)
    │     ├── enforce max_uncompressed_bytes (cumulative)
    │     └── enforce max_entries
    ├── on-write: re-resolve every target and re-check `checkout.contains()`
    └── returns ExtractionResult(file_count, total_uncompressed_bytes)
    ↓
CheckoutDir(root=<isolated temp dir under settings.uploads_dir>)
```

### GitHub path

```
GitHub URL (untrusted string)
    ↓
validate_repo_url(raw_url)  # pure, no network I/O
    ├── scheme allow-list: {https} only
    ├── host allow-list:   {github.com, www.github.com} only
    ├── reject embedded credentials (user / user:pass @)
    ├── reject local filesystem paths (/, ./, C:\)
    └── require at least owner/repo in path
    ↓
clone_repo(url, checkout, config)
    ├── shallow: depth=1, single_branch=True
    ├── kill_after_timeout=config.clone_timeout_seconds
    ├── maps git.GitCommandError:
    │     ├── status == -9 or "timeout" in stderr → CloneTimeoutError
    │     └── otherwise                            → CloneError
    └── returns CloneResult(url, cloned_to)
    ↓
CheckoutDir  (same abstraction as the ZIP path)
```

### Downstream contract

`CheckoutDir` is:

- a temp dir under `settings.uploads_dir` created via `CheckoutDir.create()`,
- a context manager with deterministic cleanup on exit,
- exposing `root: Path` (absolute, resolved) and `contains(path) -> bool` for containment checks.

Everything after ingestion (file discovery, AST parsing, extractors, persistence) **must** treat `CheckoutDir.root` as its only input and must not learn or care whether it was a ZIP or a clone.

### Security decisions (do not weaken)

- **ZIP traversal protection** — pre-flight name checks + on-write re-resolution against `checkout.contains()`.
- **Symlink rejection** — any archive entry with Unix mode `0o120000` is refused.
- **Size cap** — cumulative uncompressed size ≤ `settings.max_repo_bytes` (default 200 MiB).
- **Entry-count cap** — total entries ≤ `settings.max_files_per_repo` (default 20 000).
- **GitHub HTTPS-only** — reject `http`, `ssh`, `git`, `file`, `ftp`.
- **GitHub host allow-list** — explicit `{github.com, www.github.com}`. New hosts require an ADR update, not a code tweak.
- **No embedded credentials** — reject any URL with `user` or `user:pass` component.
- **Public repositories only** — no auth is sent. Private repos surface as `CloneError` and stay that way for the MVP.
- **Clone timeout** — `settings.clone_timeout_seconds` (default 120s). Enforced via GitPython's `kill_after_timeout`.

---

## 6. M2 Frozen Design

The full M2 design was frozen in the DeveloperJournal (§3 M2 entry). Do not re-open it. Summary:

**Objective.** Take a Python repository from an ingestion input (ZIP or GitHub URL) to persisted, citeable `code_unit` and `test_unit` rows. Deterministic. No AI, no embeddings, no Claude on the critical path.

**Persistence contract.** Writes go only into `project`, `code_unit`, `test_unit`. `dense_embedding` and `lexical_index` are populated in M4, not now. No `analysis_run` / `trace_link` / `trace_evidence` writes yet.

**Test/code split.** File-first heuristic: anything under a `tests/` directory or matching `test_*.py` / `*_test.py` becomes a `TestUnit`; everything else is a `CodeUnit`. Path-based, not per-function.

**Metadata captured now.** Per `CodeUnit`: qualified name, signature, decorators, base classes (for classes), docstring, `async` flag, line span, source snippet, `content_hash` (stable input to M4's embedding cache). Import edges captured per file as JSONB on the code unit payload — the _import graph_ is a derived read, not a new table.

**Concurrency.** Per-file parsing runs on a small process pool. Per-file failures are logged and skipped (partial success by default), never fatal for the whole ingestion.

### Steps

Completed:

- **Step 1 — Safe ZIP Ingestion + `CheckoutDir`.** _(shipped)_
- **Step 2 — GitHub Repository Cloner.** _(shipped)_

Next:

- **Step 3 — Repository File Discovery.** Walk a `CheckoutDir` with the hard ignore list, produce a bounded list of `.py` paths and their classification as code vs test.

Remaining:

- **Step 4 — AST Parser.** Turn one `.py` file into a typed intermediate representation (module, classes, functions, imports, decorators, docstrings, line spans, `content_hash`). No DB.
- **Step 5 — Extractors.** Pure functions mapping the parser IR onto `CodeUnit` / `TestUnit` domain objects.
- **Step 6 — Persistence Service.** Transactional write of one `project` + its `code_unit`s and `test_unit`s via the M0.4 session dependency.
- **Step 7 — HTTP surface.** `POST /projects` (URL or ZIP upload) + `GET /projects/{id}`. Full round-trip.
- **Step 8 — Concurrency + robustness.** Process pool for parsing, per-file failure isolation, structured error logging.

Only implement one step at a time. Stop after each for user verification.

---

## 7. Next Task — M2 Step 3

**Objective.** Given a `CheckoutDir` produced by step 1 or step 2, walk its filesystem, apply the frozen ignore list, and return a bounded, classified list of Python source files that downstream steps will parse. Deterministic, DB-free, network-free.

**Requirements (frozen):**

- Walk `CheckoutDir.root` recursively.
- Skip any directory whose name is in the hard ignore list: `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `dist`, `build`, `.tox`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`. Skip whole subtrees — do not descend into them.
- Include only files with a `.py` suffix. Reject other suffixes silently.
- Do not follow symlinks (`os.walk(followlinks=False)` or equivalent).
- Enforce a per-file size cap (reuse or add a settings-driven bound; oversized files are skipped with a log entry, not fatal).
- Classify each file as `code` or `test` using the frozen path-based heuristic:
  - `test` if any path segment (relative to `CheckoutDir.root`) equals `tests`, or the filename matches `test_*.py` or `*_test.py`.
  - `code` otherwise.
- Return a typed result (a dataclass or Pydantic model — pick whichever the existing services layer uses) with the absolute path, the path relative to `CheckoutDir.root`, and the classification. **Preserve determinism**: results must be sorted (e.g. by relative path) so a re-run over the same checkout yields identical ordering.

**Scope boundaries:**

- No AST parsing.
- No content reading beyond what a size check needs (`Path.stat()` is enough).
- No DB access.
- No new dependencies.
- Do not touch the ZIP extractor, the cloner, or `CheckoutDir` beyond consuming them.
- Do not extend `IngestionError` unless a genuinely new failure mode requires it.

**Before writing code:**

1. Inspect `backend/app/services/ingestion/` to see the existing shape (dataclasses, error hierarchy, module layout).
2. Read the M2 design in `docs/DeveloperJournal.md` §3.
3. Check `backend/app/core/config.py` for any settings you should reuse (e.g. `max_files_per_repo`) versus adding new ones.
4. Read `backend/tests/services/test_*.py` to match the testing style (real fixture directories over mocks where cheap; each threat/edge case as its own test).

**Deliverables:**

- New module: `backend/app/services/ingestion/discovery.py` (or a name consistent with the existing pattern — do not invent a subpackage).
- New tests: `backend/tests/services/test_discovery.py`.
- If a new settings field is needed (e.g. per-file size cap), add it in `app/core/config.py` and `.env.example` with a comment naming the milestone.

---

## 8. Engineering Rules

- **Inspect before modifying.** Read the surrounding module and tests before touching anything.
- **Follow `docs/ADR.md` and `docs/SystemDesign.md`.** These are the authoritative contract.
- **Strict typing throughout.** All new code passes `mypy --strict`. Prefer `from __future__ import annotations`, `Mapped[...]`, `Annotated[..., Depends(...)]`, and explicit return types on public functions.
- **Keep quality gates green.** ruff, mypy strict, pytest. Never merge a step that regresses any of them.
- **Write tests for new behavior.** Every new module ships with tests in `backend/tests/`. Match the existing style (real fixtures over mocks where cheap; one test per threat/edge case).
- **Small, milestone-scoped changes.** One M2 step per commit. Do not bundle unrelated refactors.
- **Never silently redesign frozen architecture.** If a frozen decision is genuinely wrong, stop and explain; wait for approval before changing.
- **Never implement future milestones early.** No embeddings in M2. No Claude calls before M5. No frontend integration before M7.
- **Explain architecture-changing decisions before making them.** Include the ADR/SystemDesign section you're consulting.
- **Deterministic logic before LLM reasoning.** If a check can be done in pure Python, do it there — reserve LLM calls for what only an LLM can do.
- **Secrets out of Git.** Update `.env.example` (names only); never commit `.env`.
- **Windows dev + Linux deploy compatibility.** Use `pathlib.Path`, `os.path.join`, and forward-slash-safe patterns. Line endings via `.gitattributes` if needed. Do not rely on POSIX-only APIs on the critical path.

---

## 9. Verification Baseline

Before starting M2 Step 3, from `backend/`:

```
uv run ruff check .            → All checks passed
uv run mypy app tests          → Success: no issues found in 29 source files
uv run pytest                  → 61 passed, 1 deselected
```

The `1 deselected` is `test_real_clone_from_github`, the network-marked integration test gated behind `--run-network`. Do not modify this policy.

**You must preserve or improve this baseline** on every step. If a change reduces the test count, explain why (e.g., merging two tests into a parametrized one) or restore the coverage.

---

## 10. Development Workflow

For every implementation step, follow this sequence exactly:

1. **Inspect** — read the existing modules and tests you'll be extending. Note the patterns, error types, dataclass conventions, and settings.
2. **Plan briefly** — one short paragraph naming the module to add, the public functions/types it will expose, and the tests you'll write. If new settings or dependencies are required, name them.
3. **Implement** — write the module + tests in one focused pass.
4. **Test** — run all three gates locally:
   - `uv run ruff check .`
   - `uv run mypy app tests`
   - `uv run pytest`
5. **Report changed files** — list every file created or modified with a one-line summary of what changed.
6. **Report verification results** — the exit lines of all three gates.
7. **Stop for user verification.**

**Do not automatically continue into the next major step.** After step 3, wait for explicit approval before starting step 4.

---

## 11. Future Roadmap

Post-M2, in order. Do not implement any of these until M2 is complete and the user says to.

- **M3 — Requirement Intelligence.** Requirements-doc ingestion, batched Claude call (Understand + Requirement Intelligence + Engineering Expectations = one call, ADR-003/019), `requirement` rows with the Stage 1–3 payload in `requirement_analysis` JSONB. First Claude adapter (`LLMClient`) lands here — structured outputs, retries, usage logging.
- **M4 — Embeddings & Hybrid Retrieval.** BGE-M3 embeddings into `code_unit.dense_embedding` (content-hash cached). `tsvector` population. Dense + lexical hybrid retrieval with RRF, callable per-expectation.
- **M5 — Claude Traceability Engine.** Per-expectation verdicts (Stage 4), evidence verification, deterministic confidence bands from exposed signals (ADR-010), `trace_link` + `trace_evidence` rows, matrix endpoint. **The flagship.**
- **M6 — Engineering Intelligence.** Deterministic Engineering Risk + six-dimension Business Impact + five-dimension Requirement Intelligence Score with rationales (ADR-020, ADR-022). All composers are pure functions.
- **M7 — Dashboard & Reporting.** Executive rollup (deterministic SQL + one Claude narrative call, ADR-021) into `analysis_run.executive_summary`. Full Next.js UI wired to the API (matrix, requirement detail with expectation/evidence panels, coverage, executive view).
- **M8 — Evaluation, Performance & Deployment.** Labeled dataset + eval harness (retrieval recall@k, verdict precision/recall, confidence separation). Prompt caching, cost tuning. Deployed frontend + backend.

Milestone numbering may be refined as work lands; the ordering and boundaries are frozen.

---

## 12. Important Context

- The **Anthropic API** will eventually power FlowForge's reasoning engine (starting in M3 with the requirement-analysis call, expanding in M5 for per-expectation traceability verdicts and in M7 for the executive narrative).
- **Claude Code (you) is the development assistant** — a separate concern from the Anthropic API integration that FlowForge will use at runtime.
- **Do not integrate the Anthropic API into FlowForge until M3.** No `anthropic` SDK, no API key wiring, no adapter stub. The `ANTHROPIC_API_KEY` field already exists in `Settings` as a placeholder; leave it empty and unused until then.
- The reasoning boundary (ADR-008) applies to the FlowForge runtime, not to you. Nothing about how you assist development affects the frozen architecture of the product.

---

## CURRENT TASK

Implement **M2 Step 3 — Repository File Discovery**.

Before implementation, read in order:

1. `docs/CLAUDE_HANDOFF.md` (this file).
2. `docs/ADR.md`.
3. `docs/SystemDesign.md`.
4. `docs/DeveloperJournal.md` (or `developerjournal.md` — use whichever path is present).
5. Relevant existing M2 ingestion source and tests:
   - `backend/app/services/ingestion/checkout.py`
   - `backend/app/services/ingestion/zip_extractor.py`
   - `backend/app/services/ingestion/git_cloner.py`
   - `backend/app/services/ingestion/errors.py`
   - `backend/app/core/config.py`
   - `backend/tests/services/test_checkout.py`
   - `backend/tests/services/test_zip_extractor.py`
   - `backend/tests/services/test_git_cloner.py`

Do not implement Step 3 while creating or reading this document.
