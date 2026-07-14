"""Domain enumerations.

String-valued enums frozen by the System Design (§6/§7). They are stored as
``VARCHAR + CHECK`` (``native_enum=False`` at the column) rather than native
PostgreSQL enum types, so adding a value later is a plain migration instead of
an ``ALTER TYPE`` dance. Inheriting from ``str`` makes JSON/logging trivial.
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle of an :class:`AnalysisRun` (ADR-013)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Verdict(StrEnum):
    """Aggregated implementation verdict for a (run, requirement) pair."""

    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    MISSING = "missing"
    ANALYSIS_ERROR = "analysis_error"


class ConfidenceBand(StrEnum):
    """Coarse confidence band derived deterministically from signals (ADR-010)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestStatus(StrEnum):
    """Test coverage status for a requirement's implementation."""

    COVERED = "covered"
    PARTIAL = "partial"
    UNCOVERED = "uncovered"


class EvidenceType(StrEnum):
    """Whether a piece of cited evidence is implementation code or a test."""

    IMPLEMENTATION = "implementation"
    TEST = "test"
