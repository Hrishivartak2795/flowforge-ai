"""Tests for :mod:`app.services.ingestion.persistence`.

Uses a lightweight fake session rather than a live database — no Postgres
fixture exists in this suite yet (see the Step 6 report), so these tests
cover the DTO->ORM mapping and the add_all/flush contract only. The optional
real-Postgres integration test is deferred to Step 7, when project rows and
an HTTP-level fixture are introduced.

``pytest-asyncio`` is not a project dependency, so coroutines under test are
driven directly with :func:`asyncio.run` from plain synchronous test
functions rather than via an ``@pytest.mark.asyncio`` plugin.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models import CodeUnit
from app.domain.models import TestUnit as _TestUnitORM
from app.services.ingestion.extractors import CodeUnitDTO
from app.services.ingestion.extractors import TestUnitDTO as _TestUnitDataclass
from app.services.ingestion.persistence import PersistenceResult, persist_units


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@dataclass
class FakeSession:
    """Mirrors the slice of ``AsyncSession`` this module touches."""

    added_batches: list[list[Any]] = field(default_factory=list)
    flush_calls: int = 0
    commit_calls: int = 0
    flush_error: Exception | None = None

    def add_all(self, objects: Sequence[Any]) -> None:
        self.added_batches.append(list(objects))

    async def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            raise self.flush_error
        for batch in self.added_batches:
            for obj in batch:
                if getattr(obj, "id", None) is None:
                    obj.id = uuid4()

    def commit(self) -> None:  # pragma: no cover - must never be called
        self.commit_calls += 1


def _code_dto(name: str = "f", **overrides: object) -> CodeUnitDTO:
    defaults: dict[str, object] = {
        "file_path": "mod.py",
        "unit_type": "function",
        "qualified_name": f"mod.{name}",
        "signature": "()",
        "docstring": None,
        "source_code": f"def {name}(): pass",
        "start_line": 1,
        "end_line": 2,
        "content_hash": f"hash-{name}",
    }
    defaults.update(overrides)
    return CodeUnitDTO(**defaults)  # type: ignore[arg-type]


def _test_dto(name: str = "test_f", **overrides: object) -> _TestUnitDataclass:
    defaults: dict[str, object] = {
        "file_path": "test_mod.py",
        "test_name": name,
        "qualified_name": f"test_mod.{name}",
        "source_code": f"def {name}(): pass",
        "start_line": 1,
        "end_line": 2,
    }
    defaults.update(overrides)
    return _TestUnitDataclass(**defaults)  # type: ignore[arg-type]


def _persist(
    session: FakeSession,
    project_id: UUID,
    code_units: list[CodeUnitDTO],
    test_units: list[_TestUnitDataclass],
) -> PersistenceResult:
    return _run(persist_units(session, project_id, code_units, test_units))  # type: ignore[arg-type]


class TestMappingAndPersistence:
    def test_code_and_test_units_together(self) -> None:
        session = FakeSession()
        code_units = [_code_dto("a"), _code_dto("b")]
        test_units = [_test_dto("test_a")]

        result = _persist(session, uuid4(), code_units, test_units)

        assert len(result.code_unit_ids) == 2
        assert len(result.test_unit_ids) == 1
        assert all(isinstance(i, UUID) for i in result.code_unit_ids)
        assert all(isinstance(i, UUID) for i in result.test_unit_ids)

    def test_add_all_receives_expected_objects(self) -> None:
        session = FakeSession()
        code_units = [_code_dto("a")]
        test_units = [_test_dto("test_a")]

        _persist(session, uuid4(), code_units, test_units)

        assert len(session.added_batches) == 2
        code_batch, test_batch = session.added_batches
        assert len(code_batch) == 1
        assert isinstance(code_batch[0], CodeUnit)
        assert code_batch[0].qualified_name == "mod.a"
        assert len(test_batch) == 1
        assert isinstance(test_batch[0], _TestUnitORM)
        assert test_batch[0].qualified_name == "test_mod.test_a"

    def test_flush_awaited_exactly_once(self) -> None:
        session = FakeSession()

        _persist(session, uuid4(), [_code_dto()], [_test_dto()])

        assert session.flush_calls == 1

    def test_both_empty_no_add_no_flush(self) -> None:
        session = FakeSession()

        result = _persist(session, uuid4(), [], [])

        assert result.code_unit_ids == ()
        assert result.test_unit_ids == ()
        assert session.added_batches == []
        assert session.flush_calls == 0
        assert session.commit_calls == 0

    def test_only_code_units(self) -> None:
        session = FakeSession()

        result = _persist(session, uuid4(), [_code_dto("a")], [])

        assert len(result.code_unit_ids) == 1
        assert result.test_unit_ids == ()
        assert session.flush_calls == 1

    def test_only_test_units(self) -> None:
        session = FakeSession()

        result = _persist(session, uuid4(), [], [_test_dto("test_a")])

        assert result.code_unit_ids == ()
        assert len(result.test_unit_ids) == 1
        assert session.flush_calls == 1

    def test_unit_type_propagates_verbatim(self) -> None:
        session = FakeSession()
        code_units = [
            _code_dto("f", unit_type="function"),
            _code_dto("C", unit_type="class"),
            _code_dto("m", unit_type="method"),
        ]

        _persist(session, uuid4(), code_units, [])

        unit_types = [obj.unit_type for obj in session.added_batches[0]]
        assert unit_types == ["function", "class", "method"]

    def test_none_signature_and_docstring_map_to_none(self) -> None:
        session = FakeSession()
        code_units = [_code_dto("C", signature=None, docstring=None)]

        _persist(session, uuid4(), code_units, [])

        obj = session.added_batches[0][0]
        assert obj.signature is None
        assert obj.docstring is None

    def test_embedding_and_lexical_index_never_assigned(self) -> None:
        session = FakeSession()

        _persist(session, uuid4(), [_code_dto()], [])

        obj = session.added_batches[0][0]
        assert obj.dense_embedding is None
        assert obj.lexical_index is None

    def test_returned_ids_preserve_input_order(self) -> None:
        session = FakeSession()
        code_units = [_code_dto("a"), _code_dto("b"), _code_dto("c")]
        test_units = [_test_dto("test_a"), _test_dto("test_b")]

        result = _persist(session, uuid4(), code_units, test_units)

        assert list(result.code_unit_ids) == [
            obj.id for obj in session.added_batches[0]
        ]
        assert list(result.test_unit_ids) == [
            obj.id for obj in session.added_batches[1]
        ]

    def test_flush_error_propagates(self) -> None:
        session = FakeSession(
            flush_error=IntegrityError("stmt", {}, Exception("fk violation"))
        )

        with pytest.raises(IntegrityError):
            _persist(session, uuid4(), [_code_dto()], [])

    def test_commit_never_called(self) -> None:
        session = FakeSession()

        _persist(session, uuid4(), [_code_dto()], [_test_dto()])

        assert session.commit_calls == 0
