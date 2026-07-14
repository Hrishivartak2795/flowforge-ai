"""Schema-shape tests for the domain models.

These assert the *shape* of ``Base.metadata`` — table set, the pgvector column,
enum value sets, key constraints, and cascade wiring — without touching a live
database, so they run in CI (which has no Postgres yet). End-to-end migration
behavior is verified manually against a pgvector-enabled Postgres (see the M1
verification steps).
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint

from app.domain import Base
from app.domain.enums import (
    ConfidenceBand,
    EvidenceType,
    RunStatus,
    Verdict,
)
from app.domain.enums import (
    TestStatus as _TestStatus,
)
from app.domain.models import EMBEDDING_DIM

EXPECTED_TABLES = {
    "project",
    "requirements_doc",
    "requirement",
    "code_unit",
    "test_unit",
    "analysis_run",
    "trace_link",
    "trace_evidence",
}


def test_all_tables_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_dense_embedding_is_vector_1024() -> None:
    col = Base.metadata.tables["code_unit"].c.dense_embedding
    assert isinstance(col.type, Vector)
    assert col.type.dim == EMBEDDING_DIM == 1024
    assert col.nullable is True  # populated in M4, empty now


def test_lexical_index_column_exists() -> None:
    assert "lexical_index" in Base.metadata.tables["code_unit"].c


def test_enum_values_match_frozen_design() -> None:
    assert {e.value for e in RunStatus} == {"pending", "running", "complete", "failed"}
    assert {e.value for e in Verdict} == {
        "implemented",
        "partial",
        "missing",
        "analysis_error",
    }
    assert {e.value for e in ConfidenceBand} == {"high", "medium", "low"}
    assert {e.value for e in _TestStatus} == {"covered", "partial", "uncovered"}
    assert {e.value for e in EvidenceType} == {"implementation", "test"}


def _fk_targets(table_name: str, column: str) -> set[str]:
    col = Base.metadata.tables[table_name].c[column]
    return {fk.column.table.name for fk in col.foreign_keys}


def test_core_foreign_keys() -> None:
    assert _fk_targets("requirement", "project_id") == {"project"}
    assert _fk_targets("requirement", "doc_id") == {"requirements_doc"}
    assert _fk_targets("trace_link", "run_id") == {"analysis_run"}
    assert _fk_targets("trace_link", "requirement_id") == {"requirement"}
    assert _fk_targets("trace_evidence", "code_unit_id") == {"code_unit"}
    assert _fk_targets("trace_evidence", "test_unit_id") == {"test_unit"}


def test_ownership_fks_cascade_on_delete() -> None:
    # Deleting a project (or run) must cascade to children at the DB level.
    for table, column in [
        ("requirement", "project_id"),
        ("code_unit", "project_id"),
        ("analysis_run", "project_id"),
        ("trace_link", "run_id"),
        ("trace_evidence", "trace_link_id"),
    ]:
        col = Base.metadata.tables[table].c[column]
        fk: ForeignKey = next(iter(col.foreign_keys))
        assert fk.ondelete == "CASCADE", f"{table}.{column} missing ON DELETE CASCADE"


def test_unique_constraints() -> None:
    req = Base.metadata.tables["requirement"]
    req_uniques = {
        tuple(c.name for c in con.columns)
        for con in req.constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("project_id", "external_key") in req_uniques

    link = Base.metadata.tables["trace_link"]
    link_uniques = {
        tuple(c.name for c in con.columns)
        for con in link.constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("run_id", "requirement_id") in link_uniques


def test_trace_evidence_has_xor_check() -> None:
    ev = Base.metadata.tables["trace_evidence"]
    checks = [c for c in ev.constraints if isinstance(c, CheckConstraint)]
    assert any("exactly_one_unit" in str(c.name or "") for c in checks)
