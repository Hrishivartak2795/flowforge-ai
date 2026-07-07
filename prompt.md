Good thinking — a clean handoff is the difference between a fresh session picking up in 30 seconds versus you re-explaining for 20 minutes. Here's everything.

## Which docs to give

Attach these three from your repo (in this priority order):

1. **`DeveloperJournal.md`** — the single most important one. It was built for exactly this. It contains current state, what's done, what every file does, and what's next.
2. **`ADR.md`** — the frozen architectural contract. Ensures the new session doesn't re-litigate decisions or drift.
3. **`SystemDesign.md`** — the full blueprint (folder structures, schema, API, roadmap) for when you get into real feature code.

You don't strictly need to paste code files — your **GitHub repo link** covers that, and the journal explains the structure. If a specific milestone needs a file, share it then.

Optional but helpful: the **GitHub repo URL** so it can reference actual current code if needed.

## Which model to use

**Use Opus (the most capable model) for this project.** Here's the honest reasoning:

- This is a **complex, long-horizon engineering project** with a frozen architecture that must be respected across many milestones. That's exactly where the strongest model earns its keep — it holds more context coherently, catches subtle misalignments with the ADR, and writes more production-quality code with fewer errors.
- The cheaper/faster models are great for quick edits and simple Q&A, but for architecture-aware code generation, debugging across files, and the upcoming AI-pipeline work (embeddings, retrieval, prompt design), you want the top model.
- **Practical tip:** if you ever hit usage limits on Opus mid-session, drop to Sonnet for routine steps (running commands, small edits) and switch back to Opus for anything involving design decisions or complex code. But default to Opus.

## The resume prompt

Paste this at the start of the new chat, with the three docs attached:

---

> I'm continuing a software project called **FlowForge AI** — an AI-Powered Requirements Intelligence & Engineering Decision Platform (links requirements documents to code, produces an explainable Requirement Traceability Matrix). I've attached my `DeveloperJournal.md`, `ADR.md`, and `SystemDesign.md`. My repo is at: **[YOUR GITHUB URL]**.
>
> **Read the DeveloperJournal first — it has the full current state.** In short: the architecture is **frozen** (per the ADR), and I've completed milestones **M0.1 through M0.4** (repo skeleton, backend skeleton, config + JSON logging, and Docker + Postgres/pgvector + `/health/ready`). All code is committed to GitHub.
>
> **Current status:** M0.4 code is written and committed but **not yet verified locally** — I just installed Docker Desktop and need to run `docker compose up --build` and confirm `/health/ready` works before moving on. **Next milestone is M0.5 (CI pipeline / GitHub Actions).**
>
> **Your role:** act as my **Senior Software Engineer and Technical Lead**. Keep everything aligned with the frozen ADR and System Design — do not re-open architectural decisions unless implementation reveals a real problem.
>
> **Working style (I've already learned the fundamentals, so optimize for speed):**
>
> - Keep explanations brief for infrastructure milestones; I understand FastAPI, uv, pytest, Docker, DI, the app factory, etc.
> - Slow down and explain deeply when we reach the **AI-specific milestones** (AST parsing, embeddings, pgvector retrieval, Claude integration, prompt engineering, traceability engine).
> - For each milestone: short objective → note only decisions that affect future architecture → generate the files → where each file belongs → manual testing steps → wait for my confirmation before the next milestone.
> - Use `uv`, keep ruff/mypy/pytest green, strict typing throughout. I'm on **Windows/PowerShell**.
> - After each milestone, update my `DeveloperJournal.md` (give me the full updated file to replace).
>
> **First:** help me verify M0.4 is working locally (Docker is now installed), then we proceed to M0.5.

---

Fill in `[YOUR GITHUB URL]` and you're set.

Two small things to make the handoff bulletproof:

- Before you restart, make sure that resume note's status line is **true** — i.e., you've pushed M0.4 to GitHub. (You were mid-push; confirm `git status` is clean and it's on GitHub.)
- Keep the three docs somewhere easy to grab (a downloads folder), since you'll re-attach them.

That prompt + those three docs + Opus will drop the new session into exactly the right place. Want me to also generate a tiny `RESUME.md` you can commit to the repo root that contains this same status summary, so it travels with the code and you never have to reconstruct it?
