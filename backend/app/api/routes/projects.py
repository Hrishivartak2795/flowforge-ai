"""Project ingestion + lookup — the M2 Step 7 HTTP surface.

Two write endpoints (ZIP upload, GitHub URL) drive the ingestion pipeline
end to end; one read endpoint returns project metadata plus unit counts.
Validation here is request-shape only (file present, field present/typed,
UUID well-formed) — the ingestion services own their own validation, and it
is not duplicated here.

Error responses never leak checkout paths, cloner stderr, or tracebacks: each
mapped exception gets a fixed, short ``detail`` message.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.domain.models import CodeUnit, Project, TestUnit
from app.services.ingestion.errors import (
    AllFilesFailedError,
    ArchiveTooLargeError,
    CloneError,
    CloneTimeoutError,
    IngestionError,
    InvalidArchiveError,
    InvalidRepositoryURLError,
    ParseError,
    UnsafeArchiveError,
)
from app.services.ingestion.pipeline import ingest_github, ingest_zip

router = APIRouter(tags=["projects"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


# ------------------------------------------------------------------------ DTOs


class GithubIngestRequest(BaseModel):
    """Body for the GitHub ingestion endpoint."""

    github_url: str


class IngestResponse(BaseModel):
    """Shared success shape for both ingestion endpoints."""

    id: UUID
    code_unit_count: int
    test_unit_count: int
    skipped_file_count: int


class ProjectDetailResponse(BaseModel):
    """Project metadata plus unit counts, for ``GET /projects/{id}``."""

    id: UUID
    name: str
    description: str | None
    source_repo_url: str | None
    status: str
    created_at: datetime
    code_unit_count: int
    test_unit_count: int


# --------------------------------------------------------------- error mapping

# Order matters: subclasses (CloneTimeoutError < CloneError) are checked first.
_ERROR_DETAIL: tuple[tuple[type[IngestionError], int, str], ...] = (
    (
        ArchiveTooLargeError,
        status.HTTP_413_CONTENT_TOO_LARGE,
        "archive exceeds size or file-count limit",
    ),
    (UnsafeArchiveError, status.HTTP_400_BAD_REQUEST, "unsafe archive"),
    (InvalidArchiveError, status.HTTP_400_BAD_REQUEST, "invalid archive"),
    (InvalidRepositoryURLError, status.HTTP_400_BAD_REQUEST, "invalid repository URL"),
    (CloneTimeoutError, status.HTTP_504_GATEWAY_TIMEOUT, "repository clone timed out"),
    (CloneError, status.HTTP_502_BAD_GATEWAY, "repository clone failed"),
    (ParseError, status.HTTP_422_UNPROCESSABLE_CONTENT, "failed to parse repository source"),
    (
        AllFilesFailedError,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "all discovered files failed to parse",
    ),
)

_DEFAULT_DETAIL = "ingestion failed"


def _map_ingestion_error(exc: IngestionError) -> HTTPException:
    for exc_type, status_code, detail in _ERROR_DETAIL:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status_code, detail=detail)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=_DEFAULT_DETAIL
    )


# --------------------------------------------------------------------- routes


@router.post(
    "/projects/zip",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_zip_project(
    response: Response,
    session: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
) -> IngestResponse:
    zip_bytes = await file.read()
    try:
        outcome = await ingest_zip(session, zip_bytes, settings, filename=file.filename)
    except IngestionError as exc:
        raise _map_ingestion_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal server error"
        ) from exc

    response.headers["Location"] = f"/projects/{outcome.project_id}"
    return IngestResponse(
        id=outcome.project_id,
        code_unit_count=outcome.code_unit_count,
        test_unit_count=outcome.test_unit_count,
        skipped_file_count=outcome.skipped_file_count,
    )


@router.post(
    "/projects/github",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_github_project(
    body: GithubIngestRequest,
    response: Response,
    session: DbSession,
    settings: AppSettings,
) -> IngestResponse:
    try:
        outcome = await ingest_github(session, body.github_url, settings)
    except IngestionError as exc:
        raise _map_ingestion_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal server error"
        ) from exc

    response.headers["Location"] = f"/projects/{outcome.project_id}"
    return IngestResponse(
        id=outcome.project_id,
        code_unit_count=outcome.code_unit_count,
        test_unit_count=outcome.test_unit_count,
        skipped_file_count=outcome.skipped_file_count,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: UUID, session: DbSession) -> ProjectDetailResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    code_unit_count = (
        await session.execute(
            select(func.count()).select_from(CodeUnit).where(CodeUnit.project_id == project_id)
        )
    ).scalar_one()
    test_unit_count = (
        await session.execute(
            select(func.count()).select_from(TestUnit).where(TestUnit.project_id == project_id)
        )
    ).scalar_one()

    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        source_repo_url=project.source_repo_url,
        status=project.status,
        created_at=project.created_at,
        code_unit_count=code_unit_count,
        test_unit_count=test_unit_count,
    )
