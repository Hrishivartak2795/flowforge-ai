"""Tests for :mod:`app.services.ingestion.pipeline`.

Every ingestion-service call is mocked (matching Step 6/7's testing style); a
``FakeSession`` stands in for ``AsyncSession``, supporting ``add``, ``flush``,
and an ``async with session.begin(): ...`` transaction context. No real
Postgres, no ``pytest-asyncio`` — coroutines are driven with ``asyncio.run``.

``ProcessPoolExecutor`` is replaced with ``FakeProcessPoolExecutor`` in every
test that reaches the parsing stage, so nothing here ever spawns a real
subprocess or needs to pickle a mock across a process boundary.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from concurrent.futures.process import BrokenProcessPool
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
from app.services.ingestion.errors import AllFilesFailedError, CloneError, ParseError
from app.services.ingestion.extractors import CodeUnitDTO, ExtractionUnits
from app.services.ingestion.extractors import TestUnitDTO as _TestUnitDataclass
from app.services.ingestion.persistence import PersistenceResult
from app.services.ingestion.pipeline import ingest_github, ingest_zip


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


# ------------------------------------------------------------------ fake pool


class FakeFuture:
    """Mimics ``concurrent.futures.Future`` without any real concurrency."""

    def __init__(self, value: Any = None, exc: BaseException | None = None) -> None:
        self._value = value
        self._exc = exc

    def result(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._value


class FakeProcessPoolExecutor:
    """Runs submitted work synchronously in-process; records lifecycle calls."""

    created: list[FakeProcessPoolExecutor] = []

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers
        self.entered = False
        self.exited = False
        FakeProcessPoolExecutor.created.append(self)

    def __enter__(self) -> FakeProcessPoolExecutor:
        self.entered = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.exited = True

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> FakeFuture:
        try:
            return FakeFuture(value=fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirrors real Future semantics
            return FakeFuture(exc=exc)


def _patch_pool() -> Any:
    FakeProcessPoolExecutor.created = []
    return patch(
        "app.services.ingestion.pipeline.ProcessPoolExecutor",
        FakeProcessPoolExecutor,
    )


# ---------------------------------------------------------------------- fakes


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


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "log_level": "WARNING",
        "uploads_dir": tmp_path / "uploads",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _discovered_file(
    tmp_path: Path, name: str, classification: FileClassification = FileClassification.CODE
) -> DiscoveredFile:
    absolute = tmp_path / name
    return DiscoveredFile(
        absolute_path=absolute,
        relative_path=Path(name),
        classification=classification,
    )


def _module_ir(identifier: str = "mod") -> ModuleIR:
    return ModuleIR(
        module_identifier=identifier,
        file_path=Path(f"{identifier}.py"),
        docstring=None,
        imports=(),
        functions=(),
        classes=(),
        source="",
        file_hash="hash",
    )


def _empty_units() -> ExtractionUnits:
    return ExtractionUnits(code_units=(), test_units=())


def _code_dto(name: str) -> CodeUnitDTO:
    return CodeUnitDTO(
        file_path=f"{name}.py",
        unit_type="function",
        qualified_name=f"{name}.f",
        signature="()",
        docstring=None,
        source_code="",
        start_line=1,
        end_line=1,
        content_hash=name,
    )


class TestIngestZipHappyPath:
    def test_calls_services_in_order_and_returns_outcome(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        code_dto = _code_dto("mod")
        test_dto = _TestUnitDataclass(
            file_path="test_mod.py",
            test_name="test_f",
            qualified_name="test_mod.test_f",
            source_code="def test_f(): pass",
            start_line=1,
            end_line=1,
        )

        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
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
                ingest_zip(
                    cast(AsyncSession, session), b"zip-bytes", settings, filename="repo.zip"
                )
            )

            mock_extract_zip.assert_called_once()
            mock_discover.assert_called_once()
            mock_parse.assert_called_once_with(discovered.absolute_path)
            mock_extract.assert_called_once()
            mock_persist.assert_awaited_once()

        assert outcome.code_unit_count == 1
        assert outcome.test_unit_count == 1
        assert outcome.skipped_file_count == 0
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
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
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
        assert outcome.skipped_file_count == 0
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
            ),
            pytest.raises(ParseError),
        ):
            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert not captured["checkout"].root.exists()
        assert session.begin_calls == 0
        assert session.added == []


class TestFailureBeforeTransaction:
    def test_clone_error_propagates_before_transaction(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()

        with (
            patch(
                "app.services.ingestion.pipeline.clone_repo",
                side_effect=CloneError("clone failed"),
            ),
            pytest.raises(CloneError),
        ):
            _run(ingest_github(cast(AsyncSession, session), "https://github.com/o/r", settings))

        assert session.begin_calls == 0

    def test_extractor_exception_is_fatal(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
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
                side_effect=RuntimeError("extraction exploded"),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(RuntimeError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_not_awaited()

        assert session.begin_calls == 0


class TestTransactionFailure:
    def test_persist_units_failure_rolls_back_no_commit(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
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
        assert outcome.skipped_file_count == 0
        assert session.begin_calls == 1
        assert session.commit_calls == 1


class TestOrderingAndTransactionTiming:
    def test_units_reflect_discovery_order_across_files(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        file_a = _discovered_file(tmp_path, "a.py")
        file_b = _discovered_file(tmp_path, "b.py")

        dto_a = _code_dto("a")
        dto_b = _code_dto("b")

        def _extract_side_effect(
            module: ModuleIR, relative_path: Path, classification: str
        ) -> ExtractionUnits:
            if relative_path.name == "a.py":
                return ExtractionUnits(code_units=(dto_a,), test_units=())
            return ExtractionUnits(code_units=(dto_b,), test_units=())

        with (
            _patch_pool(),
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
                side_effect=_extract_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(file_a, file_b), skipped_oversized_count=0
            )
            mock_persist.return_value = PersistenceResult(
                code_unit_ids=(uuid4(), uuid4()), test_unit_ids=()
            )

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            call_args = mock_persist.call_args
            passed_code_units = call_args.args[2]
            assert [u.qualified_name for u in passed_code_units] == ["a.f", "b.f"]

    def test_deterministic_ordering_under_out_of_order_completion(
        self, tmp_path: Path
    ) -> None:
        """Even if 'completion' order were reversed, accumulation stays in
        discovery order, because futures are consumed in submission order."""
        settings = _settings(tmp_path)
        session = FakeSession()
        file_a = _discovered_file(tmp_path, "a.py")
        file_b = _discovered_file(tmp_path, "b.py")
        file_c = _discovered_file(tmp_path, "c.py")

        modules_by_path = {
            file_a.absolute_path: _module_ir("a"),
            file_b.absolute_path: _module_ir("b"),
            file_c.absolute_path: _module_ir("c"),
        }

        def _parse_side_effect(path: Path) -> ModuleIR:
            return modules_by_path[path]

        def _extract_side_effect(
            module: ModuleIR, relative_path: Path, classification: str
        ) -> ExtractionUnits:
            return ExtractionUnits(
                code_units=(_code_dto(module.module_identifier),), test_units=()
            )

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=_parse_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.extract_units",
                side_effect=_extract_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(file_a, file_b, file_c), skipped_oversized_count=0
            )
            mock_persist.return_value = PersistenceResult(
                code_unit_ids=(uuid4(), uuid4(), uuid4()), test_unit_ids=()
            )

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            passed_code_units = mock_persist.call_args.args[2]
            assert [u.qualified_name for u in passed_code_units] == ["a.f", "b.f", "c.f"]

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


class TestPartialSuccessAndAllFailed:
    def test_partial_success_skips_failed_files_only(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        good_a = _discovered_file(tmp_path, "good_a.py")
        bad = _discovered_file(tmp_path, "bad.py")
        good_b = _discovered_file(tmp_path, "good_b.py")

        def _parse_side_effect(path: Path) -> ModuleIR:
            if path == bad.absolute_path:
                raise ParseError("bad syntax", path=path)
            identifier = "good_a" if path == good_a.absolute_path else "good_b"
            return _module_ir(identifier)

        def _extract_side_effect(
            module: ModuleIR, relative_path: Path, classification: str
        ) -> ExtractionUnits:
            return ExtractionUnits(
                code_units=(_code_dto(module.module_identifier),), test_units=()
            )

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=_parse_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.extract_units",
                side_effect=_extract_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(good_a, bad, good_b), skipped_oversized_count=0
            )
            mock_persist.return_value = PersistenceResult(
                code_unit_ids=(uuid4(), uuid4()), test_unit_ids=()
            )

            outcome = _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            passed_code_units = mock_persist.call_args.args[2]
            assert [u.qualified_name for u in passed_code_units] == [
                "good_a.f",
                "good_b.f",
            ]

        assert outcome.skipped_file_count == 1
        assert session.begin_calls == 1
        assert session.commit_calls == 1

    def test_all_files_failed_raises_and_opens_no_transaction(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        file_a = _discovered_file(tmp_path, "a.py")
        file_b = _discovered_file(tmp_path, "b.py")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=lambda path: (_ for _ in ()).throw(
                    ParseError("bad syntax", path=path)
                ),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(file_a, file_b), skipped_oversized_count=0
            )

            with pytest.raises(AllFilesFailedError) as exc_info:
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_not_awaited()

        assert exc_info.value.discovered_count == 2
        assert exc_info.value.skipped_count == 2
        assert session.begin_calls == 0
        assert session.added == []

    def test_broken_process_pool_is_fatal(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=BrokenProcessPool("pool died"),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(BrokenProcessPool):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_not_awaited()

        assert session.begin_calls == 0

    def test_non_parse_error_worker_exception_is_fatal(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=RuntimeError("unexpected worker crash"),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(RuntimeError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

            mock_persist.assert_not_awaited()

        assert session.begin_calls == 0


class TestExecutorLifecycle:
    def test_executor_created_with_configured_worker_count(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path, ingestion_parse_workers=3)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
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
            ) as mock_persist,
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert len(FakeProcessPoolExecutor.created) == 1
        assert FakeProcessPoolExecutor.created[0].max_workers == 3

    def test_executor_exits_on_all_failed_case(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "mod.py")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=ParseError("bad syntax", path=discovered.absolute_path),
            ),
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(AllFilesFailedError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        assert len(FakeProcessPoolExecutor.created) == 1
        assert FakeProcessPoolExecutor.created[0].exited is True


class TestStructuredLogging:
    def test_logs_skip_success_and_summary(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        good = _discovered_file(tmp_path, "good.py")
        bad = _discovered_file(tmp_path, "bad.py")

        def _parse_side_effect(path: Path) -> ModuleIR:
            if path == bad.absolute_path:
                raise ParseError(f"could not read {path}: boom", path=path)
            return _module_ir("good")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=_parse_side_effect,
            ),
            patch(
                "app.services.ingestion.pipeline.extract_units",
                return_value=_empty_units(),
            ),
            patch(
                "app.services.ingestion.pipeline.persist_units",
                new_callable=AsyncMock,
            ) as mock_persist,
            caplog.at_level(
                logging.DEBUG, logger="app.services.ingestion.pipeline"
            ),
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(good, bad), skipped_oversized_count=0
            )
            mock_persist.return_value = PersistenceResult(code_unit_ids=(), test_unit_ids=())

            _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        skip_records = [r for r in caplog.records if r.message == "parse.skipped"]
        assert len(skip_records) == 1
        skip_record = skip_records[0]
        assert skip_record.levelname == "WARNING"
        assert skip_record.relative_path == "bad.py"  # type: ignore[attr-defined]
        assert skip_record.error_type == "ParseError"  # type: ignore[attr-defined]
        assert str(bad.absolute_path) not in skip_record.error_message  # type: ignore[attr-defined]

        success_records = [r for r in caplog.records if r.message == "parse.success"]
        assert len(success_records) == 1
        assert success_records[0].levelname == "DEBUG"
        assert success_records[0].relative_path == "good.py"  # type: ignore[attr-defined]

        summary_records = [r for r in caplog.records if r.message == "ingestion.summary"]
        assert len(summary_records) == 1
        summary = summary_records[0]
        assert summary.levelname == "INFO"
        assert summary.discovered_count == 2  # type: ignore[attr-defined]
        assert summary.parsed_count == 1  # type: ignore[attr-defined]
        assert summary.skipped_file_count == 1  # type: ignore[attr-defined]

    def test_summary_logged_before_raising_on_all_failed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = _settings(tmp_path)
        session = FakeSession()
        discovered = _discovered_file(tmp_path, "bad.py")

        with (
            _patch_pool(),
            patch("app.services.ingestion.pipeline.extract_zip"),
            patch(
                "app.services.ingestion.pipeline.discover_python_files"
            ) as mock_discover,
            patch(
                "app.services.ingestion.pipeline.parse_python_file",
                side_effect=ParseError("bad syntax", path=discovered.absolute_path),
            ),
            caplog.at_level(
                logging.INFO, logger="app.services.ingestion.pipeline"
            ),
        ):
            mock_discover.return_value = DiscoveryResult(
                files=(discovered,), skipped_oversized_count=0
            )

            with pytest.raises(AllFilesFailedError):
                _run(ingest_zip(cast(AsyncSession, session), b"zip-bytes", settings))

        summary_records = [r for r in caplog.records if r.message == "ingestion.summary"]
        assert len(summary_records) == 1
        summary = summary_records[0]
        assert summary.discovered_count == 1  # type: ignore[attr-defined]
        assert summary.parsed_count == 0  # type: ignore[attr-defined]
        assert summary.skipped_file_count == 1  # type: ignore[attr-defined]
        assert summary.code_unit_count == 0  # type: ignore[attr-defined]
        assert summary.test_unit_count == 0  # type: ignore[attr-defined]


class TestIngestionParseWorkersSetting:
    def test_zero_workers_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ingestion_parse_workers"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                environment="test",
                log_level="WARNING",
                ingestion_parse_workers=0,
            )

    def test_negative_workers_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ingestion_parse_workers"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                environment="test",
                log_level="WARNING",
                ingestion_parse_workers=-1,
            )
