"""End-to-end ingestion: ZIP/GitHub input → persisted ``Project`` + units.

Composes Steps 1–6 into one synchronous flow reachable from the HTTP layer
(Step 7):

    checkout → materialize source → discover → parse+extract per file
    → open one DB transaction → create Project → persist units

All non-DB work (discovery, parsing, extraction) runs *before* the
transaction opens, so a failure there (e.g. :class:`ParseError`) never
creates a ``Project`` row and never opens a transaction. The checkout
directory's own context-manager cleanup (Step 1) runs on both success and
failure — nothing here re-implements it.

Out of scope, deliberately: concurrency, per-file failure isolation,
background tasks, analysis runs, import-metadata persistence, re-ingestion
dedup/upsert.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.models import Project
from app.services.ingestion.ast_parser import parse_python_file
from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.discovery import FileClassification, discover_python_files
from app.services.ingestion.extractors import (
    CodeUnitDTO,
    TestUnitDTO,
    extract_units,
)
from app.services.ingestion.git_cloner import CloneConfig, clone_repo
from app.services.ingestion.persistence import persist_units
from app.services.ingestion.zip_extractor import ExtractionLimits, extract_zip


@dataclass(frozen=True)
class IngestionOutcome:
    """Summary of one completed ingestion, for the HTTP response."""

    project_id: UUID
    code_unit_count: int
    test_unit_count: int


def _classification_literal(
    classification: FileClassification,
) -> Literal["code", "test"]:
    return "test" if classification is FileClassification.TEST else "code"


async def _collect_units(
    checkout: CheckoutDir, settings: Settings
) -> tuple[list[CodeUnitDTO], list[TestUnitDTO]]:
    """Discover, parse, and extract every source file — no DB access."""
    discovery = discover_python_files(checkout, settings)

    code_units: list[CodeUnitDTO] = []
    test_units: list[TestUnitDTO] = []

    for file in discovery.files:
        module_ir = parse_python_file(file.absolute_path)
        units = extract_units(
            module_ir,
            file.relative_path,
            _classification_literal(file.classification),
        )
        code_units.extend(units.code_units)
        test_units.extend(units.test_units)

    return code_units, test_units


async def _persist_project(
    session: AsyncSession,
    *,
    name: str,
    source_repo_url: str | None,
    code_units: list[CodeUnitDTO],
    test_units: list[TestUnitDTO],
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
            code_units, test_units = await _collect_units(checkout, settings)
            return await _persist_project(
                session,
                name=filename or "uploaded-archive",
                source_repo_url=None,
                code_units=code_units,
                test_units=test_units,
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
        code_units, test_units = await _collect_units(checkout, settings)
        return await _persist_project(
            session,
            name=github_url,
            source_repo_url=github_url,
            code_units=code_units,
            test_units=test_units,
        )
