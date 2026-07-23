"""Step 5 DTOs → the M1 ``code_unit`` / ``test_unit`` tables.

Transactional write via the frozen ``get_db_session`` DI pattern. This module
owns only the DTO→ORM mapping and the single flush; it never commits or rolls
back — that is the caller's (Step 7 HTTP surface / worker) responsibility, and
letting SQLAlchemy exceptions propagate unchanged keeps the failure visible at
the transaction boundary that owns it.

No embeddings, no import metadata (deferred — the schema has no column for
it), no project creation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CodeUnit, TestUnit
from app.services.ingestion.extractors import CodeUnitDTO, TestUnitDTO


@dataclass(frozen=True)
class PersistenceResult:
    """DB-generated IDs for the persisted units, in DTO input order."""

    code_unit_ids: tuple[UUID, ...]
    test_unit_ids: tuple[UUID, ...]


def _code_unit_orm(dto: CodeUnitDTO, project_id: UUID) -> CodeUnit:
    return CodeUnit(
        project_id=project_id,
        file_path=dto.file_path,
        unit_type=dto.unit_type,
        qualified_name=dto.qualified_name,
        signature=dto.signature,
        docstring=dto.docstring,
        source_code=dto.source_code,
        start_line=dto.start_line,
        end_line=dto.end_line,
        content_hash=dto.content_hash,
    )


def _test_unit_orm(dto: TestUnitDTO, project_id: UUID) -> TestUnit:
    return TestUnit(
        project_id=project_id,
        file_path=dto.file_path,
        test_name=dto.test_name,
        qualified_name=dto.qualified_name,
        source_code=dto.source_code,
        start_line=dto.start_line,
        end_line=dto.end_line,
    )


async def persist_units(
    session: AsyncSession,
    project_id: UUID,
    code_units: Sequence[CodeUnitDTO],
    test_units: Sequence[TestUnitDTO],
) -> PersistenceResult:
    """Add ``code_units`` and ``test_units`` to ``session`` and flush once.

    Does not commit or rollback. Empty input is a no-op (no flush, no adds).
    """
    if not code_units and not test_units:
        return PersistenceResult(code_unit_ids=(), test_unit_ids=())

    code_unit_orm_objects = [_code_unit_orm(dto, project_id) for dto in code_units]
    test_unit_orm_objects = [_test_unit_orm(dto, project_id) for dto in test_units]

    session.add_all(code_unit_orm_objects)
    session.add_all(test_unit_orm_objects)
    await session.flush()

    return PersistenceResult(
        code_unit_ids=tuple(unit.id for unit in code_unit_orm_objects),
        test_unit_ids=tuple(unit.id for unit in test_unit_orm_objects),
    )
