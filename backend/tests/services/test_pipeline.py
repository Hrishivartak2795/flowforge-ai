"""Tests for :mod:`app.services.ingestion.pipeline`.

Every ingestion-service call is mocked (matching Step 6's testing style); a
``FakeSession`` stands in for ``AsyncSession``, supporting ``add``, ``flush``,
and an ``async with session.begin(): ...`` transaction context. No real
Postgres, no ``pytest-asyncio`` — coroutines are driven with ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.ingestion.ast_parser import ModuleIR
from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.discovery import (
    DiscoveredFile,
    DiscoveryResult,
    FileClassification,
)
from app.services.ingestion.errors import CloneError, ParseError
from app.services.ingestion.extractors import CodeUnitDTO, ExtractionUnits
from app.services.ingestion.extractors import TestUnitDTO as _TestUnitDataclass
from app.services.ingestion.persistence import PersistenceResult
from app.services.ingestion.pipeline import ingest_github, ingest_zip


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeTransaction:
        self.session.begin_calls += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self.session.commit_calls += 1
        else:
            self.session.rollback_calls += 1
        return False


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_calls = 0
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
        uploads_dir=tmp_path / "uploads",
    )


def _discovered_file(
    tmp_path: Path, name: str, classification: FileClassification
) -> DiscoveredFile:
    absolute = tmp_path / name
    return DiscoveredFile(
        absolute_path=absolute,
        relative_path=Path(name),
        classification=classification,
    )


def _module_ir() -> ModuleIR:
    return ModuleIR(
        module_identifier="mod",
        file_path=Path("mod.py"),
        docstring=None,
        imports=(),
        functions=(),
        classes=(),
        source="",
        file_hash="hash",
    )


def _empty_units() -> ExtractionUnits:
    return ExtractionUnits(code_units=(), test_units=())


class TestIngestZipHappyPath:
    def test_calls_services_in_order_and_returns_outcome(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        code_dto = CodeUnitDTO(
            file_path="mod.py",
            unit_type="function",
            qualified_name="mod.f",
            signature="()",
            docstring=None,
            source_code="def f(): pass",
            start_line=1,
            end_line=1,
            content_hash="h",
        )
        test_dto = _TestUnitDataclass(
            file_path="test_mod.py",
            test_name="test_f",
            qualified_name="test_mod.test_f",
            source_code="def test_f(): pass",
            start_line=1,
            end_line=1,
        )

        discovered = _discovered_file(tmp_path, "mod.py", FileClassification.CODE)

        with (
            patch("app.services.ingestion.pipeline.extract_zip") as mock_extract_zip,
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file"
            ) as mock_parse,
            patch("app.services.ingestion.pipeline.extract_units") as mock_extract,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )
            mock_parse.return_value = _module_ir()
            mock_extract.return_value = ExtractionUnits(
                code_units=(code_dto,), test_units=(test_dto,)
            )
            mock_persist.return_value = PersistenceResult(
                code_unit_ids=(uuid4(),), test_unit_ids=(uuid4(),)
            )

            outcome = _run(
                ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings, filename="repo.zip")
            )

            mock_extract_zip.assert_called_once()
            mock_discover.assert_called_once()
            mock_parse.assert_called_once_with(discovered.absolute_path)
            mock_extract.assert_called_once()
            mock_persist.assert_awaited_once()

        assert outcome.code_unit_count == 1
        assert outcome.test_unit_count == 1
        assert isinstance(outcome.project_id, UUID)
        assert session.begin_calls == 1
        assert session.commit_calls == 1
        assert session.rollback_calls == 0

    def test_project_name_falls_back_to_placeholder(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(files=(), skipped_oversized_count=0)
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        project = session.added[0]
        assert project.name == "uploaded-archive"


class TestIngestGithubHappyPath:
    def test_calls_services_and_returns_outcome(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py", FileClassification.CODE)

        with (
            patch("app.services.ingestion.pipeline.clone_repo") as mock_clone,
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file"
            ) as mock_parse,
            patch("app.services.ingestion.pipeline.extract_units") as mock_extract,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )
            mock_parse.return_value = _module_ir()
            mock_extract.return_value = _empty_units()
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            outcome = _run(
                ingest_github(cast(AsyncSession, session), "https://github.com/o/r", settings)
            )

            mock_clone.assert_called_once()

        assert isinstance(outcome.project_id, UUID)
        assert session.added[0].source_repo_url == "https://github.com/o/r"
        assert session.added[0].name == "https://github.com/o/r"


class TestCheckoutCleanup:
    def test_cleanup_on_success(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        captured: dict[str, CheckoutDir] = {}

        real_create = CheckoutDir.create

        def _spy_create(parent: Path, **kwargs: object) -> CheckoutDir:
            ck = real_create(parent, **kwargs)  # type: ignore[arg-type]
            captured["checkout"] = ck
            return ck

        with (
            patch(
                "app.services.ingestion.pipeline.CheckoutDir.create",
                side_effect=_spy_create,
            ),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(files=(), skipped_oversized_count=0)
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert not captured["checkout"].root.exists()

    def test_cleanup_on_discovery_failure(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        captured: dict[str, CheckoutDir] = {}

        real_create = CheckoutDir.create

        def _spy_create(parent: Path, **kwargs: object) -> CheckoutDir:
            ck = real_create(parent, **kwargs)  # type: ignore[arg-type]
            captured["checkout"] = ck
            return ck

        with (
            patch(
                "app.services.ingestion.pipeline.CheckoutDir.create",
                side_effect=_spy_create,
            ),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files",
                side_effect=ParseError("boom", path=tmp_path / "x.py"),
            ),pytest.raises(ParseError)
        ):
            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert not captured["checkout"].root.exists()
        assert session.begin_calls == 0
        assert session.added == []


class TestFailureBeforeTransaction:
    def test_parse_error_aborts_before_transaction(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py", FileClassification.CODE)

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=ParseError("bad syntax", path=discovered.absolute_path),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(ParseError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_not_awaited()

        assert session.begin_calls == 0
        assert session.added == []

    def test_clone_error_propagates_before_transaction(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()

        with patch(
            "app.services.ingestion.pipeline.clone_repo",
            side_effect=CloneError("clone failed"),
        ), pytest.raises(CloneError):
            _run(ingest_github(cast(AsyncSession, session), "https://github.com/o/r", settings))

        assert session.begin_calls == 0


class TestTransactionFailure:
    def test_persist_units_failure_rolls_back_no_commit(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py", FileClassification.CODE)

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                return_value=_module_ir(),
            ),
            patch(
                "app.services.ingestion.pipeline.extract_units",
                return_value=_empty_units(),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db exploded"),
            ),
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(RuntimeError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert session.begin_calls == 1
        assert session.commit_calls == 0
        assert session.rollback_calls == 1


class TestEmptyRepository:
    def test_empty_repository_creates_project_with_zero_counts(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(files=(), skipped_oversized_count=0)
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            outcome = _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_awaited_once_with(session, session.added[0].id, [], [])

        assert outcome.code_unit_count == 0
        assert outcome.test_unit_count == 0
        assert session.begin_calls == 1
        assert session.commit_calls == 1


class TestOrderingAndTransactionTiming:
    def test_units_reflect_discovery_order_across_files(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        file_a = _discovered_file(tmp_path, "a.py", FileClassification.CODE)
        file_b = _discovered_file(tmp_path, "b.py", FileClassification.CODE)

        dto_a = CodeUnitDTO(
            file_path="a.py",
            unit_type="function",
            qualified_name="a.f",
            signature="()",
            docstring=None,
            source_code="",
            start_line=1,
            end_line=1,
            content_hash="a",
        )
        dto_b = CodeUnitDTO(
            file_path="b.py",
            unit_type="function",
            qualified_name="b.f",
            signature="()",
            docstring=None,
            source_code="",
            start_line=1,
            end_line=1,
            content_hash="b",
        )

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                return_value=_module_ir(),
            ),
            patch(
                "app.services.ingestion.pipeline.extract_units"
            ) as mock_extract,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(file_a, file_b), skipped_oversized_count=0
            )
            mock_extract.side_effect = [
                ExtractionUnits(code_units=(dto_a,), test_units=()),
                ExtractionUnits(code_units=(dto_b,), test_units=()),
            ]
            mock_persist.return_value = PersistenceResult(
                code_unit_ids=(uuid4(), uuid4()), test_unit_ids=()
            )

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            call_args = mock_persist.call_args
            passed_code_units = call_args.args[2]
            assert [u.qualified_name for u in passed_code_units] == ["a.f", "b.f"]

    def test_transaction_entered_exactly_once_after_non_db_steps(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()

        with (
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(files=(), skipped_oversized_count=0)
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert session.begin_calls == 1
