"""End-to-end ingestion: ZIP/GitHub input → persisted ``Project`` + units.

Composes Steps 1–6 into one synchronous flow reachable from the HTTP layer
(Step 7), with per-file parsing parallelized over a bounded process pool
and per-file ``ParseError``s isolated (Step 8):

    checkout → materialize source → discover → parse (pool) + extract per file
    → open one DB transaction → create Project → persist units

All non-DB work (discovery, parsing, extraction) runs *before* the
transaction opens, so a failure there (a fatal parse-worker error, or every
file failing to parse) never creates a ``Project`` row and never opens a
transaction. The checkout directory's own context-manager cleanup (Step 1)
runs on both success and failure — nothing here re-implements it.

Out of scope, deliberately: per-file/total timeouts, a long-lived executor,
background tasks, analysis runs, import-metadata persistence, re-ingestion
dedup/upsert.
"""

from __future__ import annotations

import logging
import tempfile
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.models import Project
from app.services.ingestion.ast_parser import ModuleIR, parse_python_file
from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.discovery import (
    DiscoveredFile,
    FileClassification,
    discover_python_files,
)
from app.services.ingestion.errors import AllFilesFailedError, ParseError
from app.services.ingestion.extractors import (
    CodeUnitDTO,
    TestUnitDTO,
    extract_units,
)
from app.services.ingestion.git_cloner import CloneConfig, clone_repo
from app.services.ingestion.persistence import persist_units
from app.services.ingestion.zip_extractor import ExtractionLimits, extract_zip

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionOutcome:
    """Summary of one completed ingestion, for the HTTP response."""

    project_id: UUID
    code_unit_count: int
    test_unit_count: int
    skipped_file_count: int


def _classification_literal(
    classification: FileClassification,
) -> Literal["code", "test"]:
    return "test" if classification is FileClassification.TEST else "code"


def _sanitized_error_message(exc: ParseError, file: DiscoveredFile) -> str:
    """A short, single-line message with the absolute checkout path removed."""
    message = str(exc).replace(
        str(file.absolute_path), file.relative_path.as_posix()
    )
    return message.splitlines()[0][:200]


def _parse_all(
    indexed_files: list[tuple[int, DiscoveredFile]], settings: Settings
) -> tuple[dict[int, ModuleIR], int]:
    """Parse every file in a bounded process pool, isolating ``ParseError``.

    Futures are consumed in discovery-index order, so accumulation is
    deterministic regardless of worker completion order. Any non-ParseError
    exception (including a broken pool) is fatal and propagates.
    """
    modules: dict[int, ModuleIR] = {}
    skipped_count = 0

    with ProcessPoolExecutor(max_workers=settings.ingestion_parse_workers) as pool:
        submissions: list[tuple[int, DiscoveredFile, Future[ModuleIR]]] = [
            (idx, file, pool.submit(parse_python_file, file.absolute_path))
            for idx, file in indexed_files
        ]
        for idx, file, future in submissions:
            try:
                modules[idx] = future.result()
            except ParseError as exc:
                skipped_count += 1
                logger.warning(
                    "parse.skipped",
                    extra={
                        "relative_path": file.relative_path.as_posix(),
                        "error_type": type(exc).__name__,
                        "error_message": _sanitized_error_message(exc, file),
                    },
                )
                continue
            logger.debug(
                "parse.success",
                extra={"relative_path": file.relative_path.as_posix()},
            )

    return modules, skipped_count


def _log_summary(
    *,
    discovered_count: int,
    parsed_count: int,
    skipped_count: int,
    code_unit_count: int,
    test_unit_count: int,
) -> None:
    logger.info(
        "ingestion.summary",
        extra={
            "discovered_count": discovered_count,
            "parsed_count": parsed_count,
            "skipped_file_count": skipped_count,
            "code_unit_count": code_unit_count,
            "test_unit_count": test_unit_count,
        },
    )


async def _collect_units(
    checkout: CheckoutDir, settings: Settings
) -> tuple[list[CodeUnitDTO], list[TestUnitDTO], int]:
    """Discover, parse (concurrently), and extract every source file.

    Returns ``(code_units, test_units, skipped_file_count)``. Raises
    :class:`AllFilesFailedError` when discovery found files but every one
    failed to parse (Case C) — no DB transaction should follow.
    """
    discovery = discover_python_files(checkout, settings)
    indexed_files = list(enumerate(discovery.files))
    discovered_count = len(indexed_files)

    modules: dict[int, ModuleIR] = {}
    skipped_count = 0
    if discovered_count:
        modules, skipped_count = _parse_all(indexed_files, settings)

    parsed_count = len(modules)

    if discovered_count > 0 and parsed_count == 0:
        _log_summary(
            discovered_count=discovered_count,
            parsed_count=0,
            skipped_count=skipped_count,
            code_unit_count=0,
            test_unit_count=0,
        )
        raise AllFilesFailedError(
            discovered_count=discovered_count, skipped_count=skipped_count
        )

    code_units: list[CodeUnitDTO] = []
    test_units: list[TestUnitDTO] = []
    for idx, file in indexed_files:
        module_ir = modules.get(idx)
        if module_ir is None:
            continue
        units = extract_units(
            module_ir,
            file.relative_path,
            _classification_literal(file.classification),
        )
        code_units.extend(units.code_units)
        test_units.extend(units.test_units)

    _log_summary(
        discovered_count=discovered_count,
        parsed_count=parsed_count,
        skipped_count=skipped_count,
        code_unit_count=len(code_units),
        test_unit_count=len(test_units),
    )

    return code_units, test_units, skipped_count


async def _persist_project(
    session: AsyncSession,
    *,
    name: str,
    source_repo_url: str | None,
    code_units: list[CodeUnitDTO],
    test_units: list[TestUnitDTO],
    skipped_file_count: int,
) -> IngestionOutcome:
    """Open the single write transaction: create the Project, persist units."""
    async with session.begin():
        project = Project(name=name, source_repo_url=source_repo_url)
        session.add(project)
        await session.flush()  # obtain project.id
        result = await persist_units(session, project.id, code_units, test_units)

    return IngestionOutcome(
        project_id=project.id,
        code_unit_count=len(result.code_unit_ids),
        test_unit_count=len(result.test_unit_ids),
        skipped_file_count=skipped_file_count,
    )


async def ingest_zip(
    session: AsyncSession,
    zip_bytes: bytes,
    settings: Settings,
    *,
    filename: str | None = None,
) -> IngestionOutcome:
    """Ingest an uploaded ZIP archive end to end.

    ``filename`` (the original upload name, if the client sent one) becomes
    the ``Project.name``; a placeholder is used when it is unavailable.
    """
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    limits = ExtractionLimits(
        max_uncompressed_bytes=settings.max_repo_bytes,
        max_entries=settings.max_files_per_repo,
    )

    with tempfile.NamedTemporaryFile(
        dir=settings.uploads_dir, suffix=".zip", delete=False
    ) as tmp:
        tmp.write(zip_bytes)
        zip_path = Path(tmp.name)

    try:
        with CheckoutDir.create(settings.uploads_dir) as checkout:
            extract_zip(zip_path, checkout, limits)
            code_units, test_units, skipped_count = await _collect_units(
                checkout, settings
            )
            return await _persist_project(
                session,
                name=filename or "uploaded-archive",
                source_repo_url=None,
                code_units=code_units,
                test_units=test_units,
                skipped_file_count=skipped_count,
            )
    finally:
        zip_path.unlink(missing_ok=True)


async def ingest_github(
    session: AsyncSession,
    github_url: str,
    settings: Settings,
) -> IngestionOutcome:
    """Ingest a public GitHub repository end to end."""
    config = CloneConfig(clone_timeout_seconds=settings.clone_timeout_seconds)

    with CheckoutDir.create(settings.uploads_dir) as checkout:
        clone_repo(github_url, checkout, config)
        code_units, test_units, skipped_count = await _collect_units(
            checkout, settings
        )
        return await _persist_project(
            session,
            name=github_url,
            source_repo_url=github_url,
            code_units=code_units,
            test_units=test_units,
            skipped_file_count=skipped_count,
        )
