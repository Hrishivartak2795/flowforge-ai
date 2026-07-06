# FlowForge Backend

FastAPI service for FlowForge AI, built on a pragmatic layered architecture (ADR-015):

```
api/  →  services/  →  domain/
                └── adapters/  (LLM, embedder, vectorstore — swappable, mockable)
```

Dependencies point inward; the `domain/` layer depends on nothing.

Implementation begins in **Milestone 0.2**. See [`../docs/SystemDesign.md`](../docs/SystemDesign.md) §7 for the full backend architecture.
