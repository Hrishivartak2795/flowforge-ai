# Architecture Decision Record (ADR)

**Project:** FlowForge AI — AI-Powered Requirements Intelligence & Engineering Decision Platform
**Flagship capability:** Requirement → Implementation → Test traceability, wrapped in a per-requirement reasoning pipeline (understand → intelligence → expectations → traceability → risk → impact → executive), with explainable, evidence-backed verdicts
**Scope of this record:** MVP (one-month, solo build)
**Status of document:** Frozen (v1.1 — reasoning-layer enrichment; physical architecture unchanged from v1.0)
**Last updated:** 2026-07-05

> **v1.1 amendment note.** This revision enriches the *reasoning layer only* — prompts, output schemas, JSONB storage, deterministic score composition, and UI panels. No change to the parser, embeddings, vector store, retrieval mechanics, execution model, folder architecture, or stack. Amended entries: ADR-001, 003, 009, 010, 012, 014, 016. New entries: ADR-019, 020, 021, 022.

---

## How to read this document

Each decision follows the same structure: **Context** (the problem), **Decision** (what we chose), **Alternatives considered** (with the reason each was rejected), and **Consequences** (what this commits us to, including known trade-offs). Decisions marked *Amended* were changed during the pre-freeze design review. Decisions marked *Deferred capability* are deliberately out of MVP scope with a documented upgrade path.

Once ratified, these decisions are **frozen**: they are not revisited unless implementation surfaces a concrete, demonstrated problem.

---

## ADR-001 — Product scope and positioning *(Amended v1.1)*

**Context.** The original vision spanned 8+ SDLC modules. A solo one-month build cannot deliver that with portfolio-grade quality, and the AI code-review market is already saturated with well-funded tools (CodeRabbit, Greptile, Qodo, Copilot Code Review, and others).

**Decision.** Position as **FlowForge AI — an AI-Powered Requirements Intelligence & Engineering Decision Platform**. The AI reasons about each requirement the way an experienced Business Analyst / Senior Engineer / Tech Lead / Engineering Manager would, through a per-requirement pipeline (ADR-019): Understand → Requirement Intelligence → Engineering Expectations → Traceability (flagship) → Engineering Risk → Business Impact → Executive Insights. MVP supports **Python repositories only**.

**Scope discipline (unchanged).** The physical architecture and effort envelope are those of v1.0; v1.1 enriches *reasoning*, not infrastructure. Only the flagship (extraction, retrieval, traceability) is rigorously evaluated; risk/impact/executive/intelligence outputs are advisory (ADR-016, ADR-020).

**Alternatives considered.**
- *Full SDLC platform (all modules).* Rejected: unbuildable at quality in the timebox; produces a broad, shallow, undemoable result.
- *AI code review as the headline.* Rejected: saturated market with published benchmarks; a solo project cannot compete and invites unfavorable comparison.
- *Traceability-only ("has this been implemented?").* Rejected on v1.1 review: under-uses the reasoning engine; the same pipeline can deliver decision-support insight at marginal extra cost (ADR-019).

**Consequences.** Narrow, deep, demoable, and now decision-useful to engineering managers. Differentiation comes from linking requirements to code *and* reasoning about them — the blind spot that pure code-review tools have (they cannot read requirements/tickets/docs).

---

## ADR-002 — Repository parsing: Python `ast` (standard library)

**Context.** We must convert a repo into citeable code units (function/class, file path, line span, docstring) to support evidence-backed traceability.

**Decision.** Use Python's built-in `ast` module. Extract per unit: qualified name, signature, docstring, source file, and exact line span. Wrap per-file parsing in try/except; skip-and-log files that fail (syntax errors, Python 2, generated code).

**Alternatives considered.**
- *Tree-sitter.* Rejected for MVP: adds a native dependency and generic-tree traversal for multi-language support we don't need yet. Retained as the multi-language upgrade path.
- *Regex/heuristics.* Rejected: fragile (misses decorators, nested defs, multiline signatures).
- *Full static analysis / LSP (e.g., Jedi).* Rejected: call-graph resolution is overkill for MVP granularity.

**Consequences.** Zero dependencies; docstrings available for free (aids embedding quality). No cross-file call-graph resolution — mitigated by allowing multi-unit evidence (see ADR-011). Parser sits behind a `CodeParser` interface so Tree-sitter can replace it later.

---

## ADR-003 — Requirement extraction: LLM structured extraction (chunked) *(Amended v1.1)*

**Context.** Requirement documents are free-form prose; we need atomic, ID'd requirements, and this same reasoning step now powers the combined Requirement Analysis stage.

**Decision.** Use Claude to extract atomic requirements into a validated schema, pre-chunking long documents by heading/section, preserving each requirement's **source offset**. Extraction is the first output of the **combined Requirement Analysis call** (ADR-019, Stages 1–3), which in the *same* structured response also returns the semantic frame (actor/action/object/constraints/domain/category), quality assessment, acceptance criteria, engineering expectations, and the Requirement Intelligence Score dimensions it can judge (ADR-022). One call, one schema, per requirement batch.

**Alternatives considered.**
- *Rule/NLP heuristics (modal-verb filtering).* Rejected: brittle across document styles; cannot assess quality.
- *Single-pass LLM over the whole document.* Rejected for long docs: context and cost pressure; weaker per-section grounding.
- *Separate calls per stage (extract, then frame, then quality, then expectations).* Rejected on v1.1 review: 4× the calls for no quality gain; batching into one structured call is the cost-discipline choice.

**Consequences.** Doubles as the Requirement Intelligence engine at ~one call per requirement (batch). Extraction/expectation granularity is a risk (over/under-splitting) — mitigated with few-shot examples and measured in the eval harness (extraction only; expectations are advisory, ADR-012/016).

---

## ADR-004 — Embedding model: BGE-M3

**Context.** Requirements are natural language; code is code. We need a shared vector space for retrieval, runnable locally, cheap, and easy to set up.

**Decision.** Use **BGE-M3** via Sentence Transformers, running locally.

**Alternatives considered.**
- *Code-specialized models (Nomic Embed Code, Jina code embeddings).* Strong on NL→code, but larger/heavier to run locally and do not natively provide a lexical signal.
- *Tiny general models (MiniLM-class, EmbeddingGemma-300M).* Faster, but lower ceiling; retained as the low-resource fallback.
- *API embeddings (voyage-code-3, OpenAI text-embedding-3).* Higher quality with less setup, but add a paid external dependency; retained as an escape hatch.

**Consequences.** Decisive advantage: BGE-M3 emits **dense and sparse vectors in one pass**, supplying both halves of hybrid retrieval (ADR-007) from a single model. Long context (8192) fits whole functions. Trade-off: ~560M params → slower on CPU-only for large repos; acceptable at MVP repo sizes. Sits behind an `Embedder` interface.

---

## ADR-005 — Code representation: raw enriched-code embeddings *(Amended)*

**Context.** We must decide *what text* we embed for each code unit.

**Decision.** Embed the **raw code unit enriched with its name, signature, and docstring**. LLM-generated natural-language summaries of code are **deferred** to an optional, eval-gated enhancement.

**Alternatives considered.**
- *Summary-embeddings as primary (original recommendation).* Rejected on review: adds an LLM call per unit (cost/latency) and introduces a silent hallucination surface — a wrong summary poisons retrieval invisibly.

**Consequences.** Simpler, cheaper, no pre-analysis hallucination risk. If retrieval quality proves insufficient on the eval set, summary-embeddings can be A/B tested as an add-on.

---

## ADR-006 — Vector store: pgvector

**Context.** We need to store and similarity-search embeddings. PostgreSQL is already the system database.

**Decision.** Use the **pgvector** extension in PostgreSQL.

**Alternatives considered.**
- *FAISS (original stack).* Rejected: it is an index, not a database — no metadata, requires separate persistence and ID reconciliation with Postgres. Its scale advantage is invisible at our volume (thousands of vectors). Retained as the >1M-vector upgrade path.
- *Chroma.* Rejected: a second service duplicating what pgvector does inside the DB we already run.
- *Qdrant / Weaviate / Pinecone.* Rejected: overkill / managed / paid.

**Consequences.** One datastore; transactional consistency between a code unit's metadata and its vector; trivial deploy. This deviates from the originally listed stack — a deliberate "boring, appropriate technology" choice.

---

## ADR-007 — Retrieval: single-model hybrid (dense + sparse)

**Context.** Pure semantic retrieval misses exact-identifier matches (a requirement about email validation should surface a function literally named `validate_email`); pure lexical misses paraphrase.

**Decision.** **Hybrid retrieval** combining BGE-M3 dense similarity with its sparse/lexical signal, fused into a ranked candidate set passed to Claude. One-directional (code-for-requirement).

**Alternatives considered.**
- *Pure vector top-k.* Rejected: misses exact identifier hits.
- *Separate BM25 lexical system.* Rejected: unnecessary second system since BGE-M3 provides sparse vectors natively.
- *Cross-encoder / LLM reranking.* Deferred capability: improves candidate precision; scoped as the week-3 stretch if time allows.

**Consequences.** Retrieval quality is the ceiling on verdict accuracy, so retrieval recall@k is measured **independently** in the eval harness. Bidirectional retrieval deferred.

---

## ADR-008 — Reasoning engine: Claude only; Sentence Transformers for embeddings only

**Context.** We must draw a clean boundary between representation and judgment.

**Decision.** **Sentence Transformers performs embedding only** (no judgments). **Claude performs all reasoning** — extraction, ambiguity analysis, and traceability verdicts. No component makes an "implemented/not" decision except Claude, and only with attached evidence.

**Alternatives considered.**
- *Threshold-based "implemented" calls from similarity scores.* Rejected: that is reasoning, and it belongs to Claude with evidence; a raw similarity threshold is neither explainable nor reliable.

**Consequences.** Textbook separation of concerns; preserves the "Claude is the only reasoning engine" property end to end.

---

## ADR-009 — Claude prompting strategy *(Amended v1.1)*

**Context.** The reasoning pipeline (ADR-019) uses Claude in three prompt roles. All must be reliable, explainable, schema-valid, and cost-controlled.

**Three prompt roles (fixed call budget).**
- **A — Requirement Analysis** (Stages 1–3): one structured call per requirement (batched) → frame, quality, acceptance criteria, expectations, judgable intelligence dimensions. *Tier: Haiku.*
- **B — Traceability verdict** (Stage 4): one structured call **per engineering expectation**, over that expectation's retrieved candidates → implemented/partial/missing + reasoning + citations + self-confidence. *Tier: Sonnet.*
- **C — Executive narrative** (Stage 7): one structured call **per project run** summarizing the deterministic rollup. *Tier: Sonnet.*

Net call budget ≈ **1 (analysis) + N_expectations (verdicts) per requirement + 1 per run**. Risk/Impact/Intelligence composites are **deterministic** (ADR-020, ADR-022) — no calls.

**Cross-cutting decisions (unchanged).**
1. **System prompt** per role: role framing, rubric, anti-hallucination rules ("cite only provided candidates; 'Missing' is expected and correct"), 2–3 few-shot examples — a stable, cacheable prefix.
2. **Structured outputs** (enforced JSON schema) so every response is well-formed.
3. **Prompt caching** on each role's stable prefix; only the per-item content varies (cache reads bill at a fraction of input cost).
4. **Model tiering** as above; explicit `max_tokens` per call.
5. **Semantic validation + retry** on top of schema validity (e.g., reject "Implemented" with no cited snippet).
6. **Low temperature** for determinism.

**Alternatives considered.**
- *One mega-prompt (all requirements + whole repo).* Rejected: violates focused-context principle; degrades quality; expensive.
- *Seven separate calls per requirement (one per stage).* Rejected on v1.1 review: the single biggest self-inflicted cost/latency wound for no quality gain; batched into three roles instead.
- *"Please return JSON" + hand-rolled parsing/repair.* Rejected: structured outputs eliminates the malformed-JSON failure class natively.
- *Agentic tool-use loop (model fetches more code on demand).* Deferred capability.

**Consequences.** Focused, parallelizable, explainable, cost-bounded. Per-expectation verdicts also make Stage-4 retrieval sharper (each expectation is a tighter query than a whole requirement). Per-call `usage` is logged (ADR-017).

---

## ADR-010 — Confidence scoring: coarse bands, explainable signals *(Amended v1.1)*

**Context.** Every verdict must carry a confidence signal, but the labeled eval set will be small (~50–150 links). Per v1.1, confidence must also be *explainable* — the user should see why a verdict is High vs Low.

**Decision.** Emit **coarse bands (High / Medium / Low)** from a deterministic composite of four **exposed signals**, stored and displayed rather than discarded: (1) **retrieval quality** (top candidate absolute similarity), (2) **evidence strength** (retrieval margin, top-1 vs top-2), (3) **implementation matches** (how many of the requirement's expectations were satisfied), and (4) **reasoning confidence** (the model's self-report). The band is a fixed weighted combination of these; each verdict stores the signal breakdown (`confidence_signals` JSONB, ADR-014). Validate **directionally** against the eval set (do High-band verdicts outperform Low?).

**Alternatives considered.**
- *LLM self-reported numeric confidence alone.* Rejected: poorly calibrated, overconfident, arbitrary — and opaque.
- *Precisely calibrated probability (reliability curve).* Rejected for MVP: sample size cannot support it; overstates rigor.
- *Opaque band (no signal breakdown).* Rejected on v1.1 review: contradicts the explainability thesis; exposing signals is nearly free and strengthens trust.

**Consequences.** Honest, defensible, buildable, and now transparent — the confidence itself is auditable. Precise calibration becomes viable later with more labeled data.

---

## ADR-011 — Explainability: evidence-backed verdicts, "Not found" first-class

**Context.** Trust is the product. No verdict may be unsourced.

**Decision.** Every trace verdict carries **evidence** (cited file(s) + line spans, and the specific lines relied upon), **reasoning**, a **confidence band**, and **provenance** (requirement's document offset; code unit's file/line). A verdict may cite **multiple** code units (distributed implementations). **"Not found" is a first-class, encouraged outcome.**

**Alternatives considered.**
- *Score-only output (verdict + number, no evidence).* Rejected: not explainable; not auditable; defeats the product thesis.

**Consequences.** Constrains the schema (ADR-014) and the prompt (ADR-009). Enables human/eval checking of evidence *correctness*, not just presence.

---

## ADR-012 — Requirement Intelligence scope: advisory vs. factual boundary *(Amended v1.1)*

**Context.** The Requirement Intelligence stage produces ambiguity flags, acceptance criteria, engineering expectations, inferred hidden requirements, and edge cases — with very different reliability profiles. Some are verifiable; some have no ground truth.

**Decision.** Draw a hard line between **factual outputs** and **advisory suggestions**:
- **Factual / evaluated:** requirement extraction, ambiguity flags (human-verifiable), and all Stage-4 traceability verdicts.
- **Advisory / displayed-not-scored:** acceptance criteria, engineering expectations, inferred hidden requirements, and suggested edge cases. These render as *"an experienced engineer would also expect…"* suggestions the user evaluates — **never as factual defect claims** ("REQ-005 is incomplete").
- **Deferred:** **contradiction detection** is out of the MVP — it is cross-requirement (N² / holistic), the only Intelligence item that isn't per-requirement, and thus a real cost/architecture addition. If implemented later, it is one holistic advisory pass, clearly labeled.

**Alternatives considered.**
- *Ship missing-requirement / completeness as factual verdicts.* Rejected: no ground truth; the model always produces plausible "missing" items; false confidence erodes trust in the reliable features.
- *Include contradiction detection in MVP.* Rejected on v1.1 review: cross-requirement comparison is not free and does not fit the per-requirement pipeline or the month.

**Consequences.** Protects credibility: the reliable outputs stay reliable, and the generative-but-unverifiable outputs are honestly framed. Expectations still feed Stage-4 retrieval (they make it sharper) even while being advisory to the user.

---

## ADR-013 — Execution model: async background task + Postgres job status *(New)*

**Context.** A full analysis takes minutes and cannot run inside a blocking HTTP request.

**Decision.** Client starts an analysis → API creates an **`AnalysisRun` (status `pending`)** and runs the pipeline in a **FastAPI background task** → client **polls a status endpoint** → results render when `complete`. Status transitions: `pending → running → complete | failed`.

**Alternatives considered.**
- *Synchronous request.* Rejected: times out; poor UX.
- *Celery + Redis (or other broker).* Rejected: over-engineering for a solo MVP; background task + a status row is sufficient.

**Consequences.** Shapes the API (ADR needs a start + status + results endpoint set) and the schema (run table). Broker-based queuing is the horizontal-scale upgrade path.

---

## ADR-014 — Persistence & schema: normalized core + JSONB evidence + run versioning

**Context.** We must store projects, artifacts, and rich, versioned, explainable trace links.

**Decision.** Normalized tables — `Project`, `RequirementsDoc`, `Requirement`, `CodeUnit`, `TestUnit`, `AnalysisRun`, `TraceLink`, `TraceEvidence` — with flexible model output stored as **JSONB**. Embeddings live in **pgvector** columns on `CodeUnit`. Provenance columns on all artifacts. **v1.1 adds JSONB fields only — no new tables:**
- `requirement.requirement_analysis` — semantic frame, quality assessment, acceptance criteria, engineering expectations (advisory), and the LLM-judged intelligence dimensions (clarity/completeness/testability).
- `trace_link.confidence_signals` — the exposed confidence breakdown (retrieval quality, evidence strength, implementation matches, reasoning confidence; ADR-010).
- A per-requirement rollup carrying `intelligence_score` (5 dimensions; ADR-022), `engineering_risk`, and `business_impact` (deterministic; ADR-020) — stored as JSONB on the `TraceLink` row (which is already one-per-run-per-requirement) or an equivalent per-requirement run row.
- `analysis_run.executive_summary` — the Stage-7 rollup (ADR-021).

**Alternatives considered.**
- *New tables per new output (risk, impact, intelligence).* Rejected on v1.1 review: these are per-requirement-per-run attributes with evolving shape; JSONB on the existing per-requirement row is the ADR-014-consistent choice and avoids a relational redesign.
- *Document store / NoSQL.* Rejected: loses the relational joins needed to assemble the matrix, and adds a datastore.

**Consequences.** Queryable matrix + flexible reasoning payloads, one migration, zero new tables. `run_id` makes re-run history/drift a later addition rather than a migration.

---

## ADR-015 — Architecture style: pragmatic layered + selective adapters

**Context.** The brief values clean architecture but warns against over-engineering the MVP.

**Decision.** Layered structure — `api/` (routes), `services/` (orchestration), `domain/` (models + trace logic), `adapters/` (**LLM, embedder, vectorstore** only), plus `eval/` and `tests/`. Monorepo split into `backend/` and `frontend/`.

**Alternatives considered.**
- *Flat structure.* Rejected: reads as an assignment, not a product.
- *Full hexagonal / ports-and-adapters everywhere (incl. parser, git).* Rejected: ceremony outweighs payoff at this size; adapters reserved for the components actually mocked/swapped.

**Consequences.** Demonstrates clean-architecture thinking (dependencies point inward; AI layer is mockable/swappable) without boilerplate tax.

---

## ADR-016 — Evaluation harness: mandatory, scoped to the flagship *(Amended v1.1)*

**Context.** Without measurement, reliability claims are unfounded — and the harness is the project's strongest credibility signal. v1.1 adds several *advisory* outputs that have no ground truth; the eval scope must stay flat.

**Decision.** Rigorously evaluate **only the factual flagship**: a labeled sample project + a one-command eval script reporting extraction quality, **retrieval recall@k**, verdict **precision/recall** (now measurable at expectation granularity), and confidence-band separation. Ground truth labeled **independently of the prompt logic**. The advisory outputs (expectations, acceptance criteria, engineering risk, business impact, executive insights, the LLM-judged intelligence dimensions) are **displayed but not scored** — they are decision-support, not classification, and inventing metrics for them would be dishonest.

**Alternatives considered.**
- *Demo-only validation.* Rejected: no evidence the system works.
- *Attempt to score risk/impact/executive outputs.* Rejected on v1.1 review: no ground truth exists; a fabricated accuracy number is worse than an honest "advisory."
- *Label using the same heuristics the prompts encode.* Rejected: leakage inflates metrics.

**Consequences.** Eval burden stays flat while the product gets richer. Enables error decomposition (retrieval vs. verdict) and defensible interview claims about the parts that are actually measured.

---

## ADR-017 — Observability & determinism

**Context.** LLM cost/behavior must be visible and demos must be reproducible.

**Decision.** Log every LLM call's prompt, response, token counts, cost, and latency (read the API `usage` object). Use low temperature and **persist results** so a demo replays identically.

**Alternatives considered.**
- *No instrumentation.* Rejected: undebuggable cost/behavior; weaker engineering story.

**Consequences.** "Cost per analysis" and cache hit-rate become reportable metrics.

---

## ADR-018 — Core stack: FastAPI + Next.js + PostgreSQL + Docker + CI

**Context.** Deliverable must look like a real product, deployable, with a demo URL.

**Decision.** FastAPI (backend), Next.js/React/TypeScript/Tailwind (frontend), PostgreSQL + pgvector (data), Docker + one GitHub Actions workflow (build/test), deployed frontend + backend.

**Alternatives considered.**
- *Heavier infra (Kubernetes, multi-service).* Rejected: no scale need; over-engineering.
- *Auth / multi-tenancy for MVP.* Rejected: single-user; zero demo value. Documented as an intentional cut.

**Consequences.** Portfolio-grade footprint without operational overhead.

---

## ADR-019 — Per-requirement reasoning pipeline *(New v1.1)*

**Context.** Traceability alone under-uses the reasoning engine. We want Business-Analyst-through-Engineering-Manager reasoning per requirement — without new infrastructure.

**Decision.** A seven-stage pipeline, implemented purely in the reasoning layer over the existing components: **(1) Understand** + **(2) Requirement Intelligence** + **(3) Engineering Expectations** = one batched Claude call (ADR-003/009 role A); **(4) Traceability** = existing hybrid retrieval + Claude verdict, run **per engineering expectation** (role B); **(5) Engineering Risk** + **(6) Business Impact** = deterministic composites (ADR-020); **(7) Executive Insights** = deterministic rollup + one narrative call (ADR-021, role C). Stage 3 expectations become the retrieval queries for Stage 4, improving flagship accuracy.

**Alternatives considered.**
- *Keep traceability-only.* Rejected: leaves the platform's most valuable reasoning on the table.
- *Seven discrete LLM calls per requirement.* Rejected: cost/latency/effort with no quality gain (ADR-009).

**Consequences.** Richer product, same physical architecture; new logic lives in `services/` + `prompts/`. Effort lands mainly on M5/M7 (see System Design roadmap); week-4 buffer shrinks but the flagship still lands.

---

## ADR-020 — Engineering Risk & Business Impact: deterministic composites *(New v1.1)*

**Context.** Managers want risk/impact signals, but LLM-invented scores are a hallucination surface and (for compliance/audit) confidently wrong.

**Decision.** Compute **Engineering Risk** and **Business Impact** as **deterministic** High/Med/Low bands from already-computed signals (implementation gap, test gap, requirement quality/ambiguity, confidence), each accompanied by a short Claude-written *rationale* (not a number the model invents). **Business Impact dimensions (MVP):** Engineering Rework, Release Delay Risk, Production Defect Risk, Testing Effort, Maintenance Effort, Engineering Priority. **Compliance and audit risk are explicitly excluded** from the MVP (regulatory assessment is out of scope; focus is engineering decision support).

**Alternatives considered.**
- *LLM-generated risk/impact scores.* Rejected: no ground truth; overconfident; a new hallucination surface.
- *Include compliance/audit.* Rejected per owner decision: out of MVP scope; the model would guess authoritatively.
- *Fabricated financial estimates.* Rejected by product vision: decision support, not forecasting.

**Consequences.** Transparent, defensible, reuses ADR-010's philosophy. Reasoning provided; scores are auditable composites.

---

## ADR-021 — Executive Insights: deterministic rollup + narrative *(New v1.1)*

**Context.** Engineering managers need project-level health at a glance, not just a per-requirement matrix.

**Decision.** Aggregate per-requirement results (SQL) into project-level metrics — overall requirement quality, implementation coverage, testing coverage, aggregate engineering risk, highest-priority requirements, and recommended engineering actions — plus **one** Claude narrative call (ADR-009 role C) that summarizes the computed rollup. Stored in `analysis_run.executive_summary` (ADR-014).

**Alternatives considered.**
- *Matrix only.* Rejected: misses the manager-facing payoff.
- *LLM-computed aggregates.* Rejected: aggregation is deterministic SQL; the LLM only narrates the numbers.

**Consequences.** High-value view at near-zero cost (data already exists once Stages 1–5 run).

---

## ADR-022 — Requirement Intelligence Score: multi-dimensional *(New v1.1)*

**Context.** A single quality number hides where a requirement is weak. Managers need to spot weak/high-risk requirements fast.

**Decision.** Score each requirement across **five dimensions**: **Clarity, Completeness, Testability** (LLM-judged advisory bands from the Requirement Analysis call, ADR-003) and **Traceability, Implementation Coverage** (deterministic, from Stage-4 verdicts). Presented as a small per-requirement profile, aggregated into the executive view. Advisory dimensions are labeled as such (ADR-012/016).

**Alternatives considered.**
- *Single scalar quality score.* Rejected: opaque; hides the weak dimension.
- *All five dimensions LLM-scored.* Rejected: Traceability and Coverage are measurable deterministically — no reason to guess them.

**Consequences.** Managers scan a profile, not a number. Two of five dimensions are hard metrics; three are advisory — honestly distinguished in the UI.

---

## Deferred capabilities (documented upgrade paths, not MVP)

Tree-sitter / multi-language · summary-embeddings · reranking · bidirectional retrieval · agentic tool-use verdicts · precise confidence calibration · **contradiction detection (cross-requirement)** · **compliance/audit risk assessment** · factual completeness/missing-requirement verdicts · re-run drift analysis · authentication/multi-tenancy · message-broker queuing · the later modules (architecture review, bug analysis, health dashboard, release readiness, technical debt).

## Freeze statement

ADR-001 through ADR-022 are **frozen** (v1.1). They will not be revisited unless implementation reveals a concrete, demonstrated problem, at which point the affected ADR is amended with a dated note rather than silently changed. v1.1 changed the reasoning layer only; the v1.0 physical architecture (parser, embeddings, vector store, retrieval, execution model, folder structure, stack) is unchanged.
