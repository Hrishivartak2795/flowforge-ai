"""Domain layer: ORM models, enums, and the declarative base.

Dependency-free and importable everywhere (System Design §7). Importing this
package registers all models on ``Base.metadata`` — which is what Alembic's
autogenerate and the app both target.
"""

from __future__ import annotations

from app.domain.base import Base
from app.domain.enums import (
    ConfidenceBand,
    EvidenceType,
    RunStatus,
    TestStatus,
    Verdict,
)
from app.domain.models import (
    AnalysisRun,
    CodeUnit,
    Project,
    Requirement,
    RequirementsDoc,
    TestUnit,
    TraceEvidence,
    TraceLink,
)

__all__ = [
    "Base",
    "RunStatus",
    "Verdict",
    "ConfidenceBand",
    "TestStatus",
    "EvidenceType",
    "Project",
    "RequirementsDoc",
    "Requirement",
    "CodeUnit",
    "TestUnit",
    "AnalysisRun",
    "TraceLink",
    "TraceEvidence",
]
