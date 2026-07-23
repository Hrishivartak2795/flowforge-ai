"""Ingestion — deterministic I/O for repository inputs.

Step 1 of M2. Turns a repository input (ZIP now; GitHub URL next) into a bounded,
locally-materialized *checkout directory* that the parser walks. Concerns:

- **Safety.** Refuse traversal (``zip-slip``), symlinks, oversized archives, or
  archives with too many entries. Every write is bounded before it happens.
- **Isolation.** Each ingestion gets its own temp dir under ``settings.uploads_dir``
  and is cleaned up deterministically.
- **Determinism.** No AI, no DB writes, no repo code execution. Just bytes on disk.
"""
