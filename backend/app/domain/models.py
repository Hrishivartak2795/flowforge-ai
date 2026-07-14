"""SQLAlchemy 2.x ORM models — the FlowForge persistence layer.

Implements the frozen schema (System Design §6). Eight tables:
``project`` and its owned children (``requirements_doc``, ``requirement``,
``code_unit``, ``test_unit``, ``analysis_run``), plus the per-run verdicts
(``trace_link``) and their multi-unit evidence (``trace_evidence``).

Conventions applied uniformly:
- UUID primary keys generated DB-side via ``gen_random_uuid()`` (Postgres 13+ core).
- ``timestamptz`` audit columns defaulted DB-side via ``now()``.
- Ownership foreign keys use ``ON DELETE CASCADE`` with ``passive_deletes=True``
  so the database performs cascades, not the ORM.
- Enums stored as ``VARCHAR + CHECK`` (``native_enum=False``).
- Model payloads (analysis output, signals, scores) live in ``JSONB`` (ADR-014).
- ``code_unit.dense_embedding`` is ``vector(1024)`` (BGE-M3) and
  ``code_unit.lexical_index`` is ``tsvector`` — created now, populated in M4.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.base import Base
from app.domain.enums import (
    ConfidenceBand,
    EvidenceType,
    RunStatus,
    TestStatus,
    Verdict,
)

# Embedding dimensionality for BGE-M3 dense vectors (System Design §6).
EMBEDDING_DIM = 1024


def _enum(enum_cls: type[Enum], name: str, length: int = 20) -> SAEnum:
    """A VARCHAR + CHECK enum column that stores the enum's lowercase *value*.

    ``native_enum=False`` keeps it as VARCHAR (easy to evolve); ``values_callable``
    persists ``.value`` (e.g. ``"pending"``) rather than the member name.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        name=name,
        length=length,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key defaulted DB-side by ``gen_random_uuid()``."""
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )


def _created_at() -> Mapped[datetime]:
    """A non-null ``timestamptz`` audit column defaulted to ``now()``."""
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Project(Base):
    """Top-level container: one uploaded requirements doc + one repo under analysis."""

    __tablename__ = "project"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_repo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="created"
    )
    created_at: Mapped[datetime] = _created_at()

    documents: Mapped[list[RequirementsDoc]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    code_units: Mapped[list[CodeUnit]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    test_units: Mapped[list[TestUnit]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class RequirementsDoc(Base):
    """Raw uploaded requirements document; source of extracted requirements."""

    __tablename__ = "requirements_doc"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uploaded_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="documents")
    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Requirement(Base):
    """Atomic requirement with quality flags, provenance, and Stage 1–3 analysis."""

    __tablename__ = "requirement"
    __table_args__ = (
        UniqueConstraint("project_id", "external_key", name="external_key"),
        Index("ix_requirement_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("requirements_doc.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_key: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    req_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_ambiguous: Mapped[bool] = mapped_column(
        nullable=False, server_default=sa_text("false")
    )
    ambiguity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Location in the source document (page/section/char offsets).
    source_offset: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Stage 1–3 payload: semantic frame, acceptance criteria, expectations, intel dims.
    requirement_analysis: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="requirements")
    document: Mapped[RequirementsDoc | None] = relationship(
        back_populates="requirements"
    )
    trace_links: Mapped[list[TraceLink]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan", passive_deletes=True
    )


class CodeUnit(Base):
    """Citeable unit of implementation (function/method/class) with retrieval columns."""

    __tablename__ = "code_unit"
    __table_args__ = (
        Index("ix_code_unit_lexical_index", "lexical_index", postgresql_using="gin"),
        Index(
            "ix_code_unit_dense_embedding",
            "dense_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"dense_embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    unit_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qualified_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int | None] = mapped_column(nullable=True)
    end_line: Mapped[int | None] = mapped_column(nullable=True)
    # Embedding cache key (skip re-embedding unchanged units on re-runs).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Populated in M4 — created now, left empty in M1.
    dense_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    lexical_index: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="code_units")


class TestUnit(Base):
    """Citeable unit of test coverage."""

    __tablename__ = "test_unit"
    __table_args__ = (Index("ix_test_unit_file_path", "file_path"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    test_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualified_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int | None] = mapped_column(nullable=True)
    end_line: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="test_units")


class AnalysisRun(Base):
    """One analysis execution; the versioning anchor for verdicts (ADR-013/014)."""

    __tablename__ = "analysis_run"
    __table_args__ = (
        Index("ix_analysis_run_project_status", "project_id", "status"),
        Index("ix_analysis_run_project_started", "project_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"),
        nullable=False,
        server_default=RunStatus.PENDING.value,
    )
    model_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Stage 7 executive rollup (ADR-021).
    executive_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped[Project] = relationship(back_populates="analysis_runs")
    trace_links: Mapped[list[TraceLink]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class TraceLink(Base):
    """One aggregated verdict per (run, requirement) — the matrix row."""

    __tablename__ = "trace_link"
    __table_args__ = (
        UniqueConstraint("run_id", "requirement_id", name="run_requirement"),
        Index("ix_trace_link_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("requirement.id", ondelete="CASCADE"),
        nullable=False,
    )
    implementation_verdict: Mapped[Verdict | None] = mapped_column(
        _enum(Verdict, "verdict"), nullable=True
    )
    implementation_confidence_band: Mapped[ConfidenceBand | None] = mapped_column(
        _enum(ConfidenceBand, "confidence_band", length=10),
        nullable=True,
    )
    implementation_confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    # Four exposed confidence signals (ADR-010).
    confidence_signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Per-expectation verdicts feeding the aggregate (ADR-019).
    expectation_results: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    # Five-dimension intelligence score (ADR-022).
    intelligence_score: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Deterministic bands + rationale (ADR-020).
    engineering_risk: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    business_impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    test_status: Mapped[TestStatus | None] = mapped_column(
        _enum(TestStatus, "test_status"),
        nullable=True,
    )
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_model_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    run: Mapped[AnalysisRun] = relationship(back_populates="trace_links")
    requirement: Mapped[Requirement] = relationship(back_populates="trace_links")
    evidence: Mapped[list[TraceEvidence]] = relationship(
        back_populates="trace_link", cascade="all, delete-orphan", passive_deletes=True
    )


class TraceEvidence(Base):
    """Multi-unit evidence cited by a verdict (ADR-011).

    Each row references exactly one of ``code_unit_id`` / ``test_unit_id``,
    enforced by a CHECK constraint.
    """

    __tablename__ = "trace_evidence"
    __table_args__ = (
        CheckConstraint(
            "(code_unit_id IS NOT NULL) <> (test_unit_id IS NOT NULL)",
            name="exactly_one_unit",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_link_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trace_link.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("code_unit.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    test_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_unit.id", ondelete="CASCADE"),
        nullable=True,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        _enum(EvidenceType, "evidence_type"),
        nullable=False,
    )
    cited_lines: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    trace_link: Mapped[TraceLink] = relationship(back_populates="evidence")
