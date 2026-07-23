"""Tests for the M2 Step 7 HTTP surface (``/projects/*``).

Pipeline functions (``ingest_zip``, ``ingest_github``) are mocked so these
tests exercise HTTP wiring — status codes, response shapes, error mapping —
not pipeline internals (covered by ``tests/services/test_pipeline.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db_session
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
from app.services.ingestion.pipeline import IngestionOutcome


class _NullSession:
    """A placeholder DB session for routes whose pipeline call is mocked."""


async def _null_session() -> AsyncIterator[_NullSession]:
    yield _NullSession()


class _FakeCountResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeProject:
    def __init__(self, project_id: Any) -> None:
        self.id = project_id
        self.name = "octocat/hello-world"
        self.description = None
        self.source_repo_url = "https://github.com/octocat/hello-world"
        self.status = "created"
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeProjectSession:
    def __init__(
        self, project: _FakeProject | None, code_count: int = 0, test_count: int = 0
    ) -> None:
        self.project = project
        self._counts = [code_count, test_count]
        self._idx = 0

    async def get(self, _model: object, _id: object) -> _FakeProject | None:
        return self.project

    async def execute(self, _stmt: object) -> _FakeCountResult:
        value = self._counts[self._idx]
        self._idx += 1
        return _FakeCountResult(value)


class TestIngestZip:
    def test_valid_upload_returns_201(self, app: FastAPI, client: TestClient) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        project_id = uuid4()
        try:
            with patch(
                "app.api.routes.projects.ingest_zip", new_callable=AsyncMock
            ) as mock_ingest:
                mock_ingest.return_value = IngestionOutcome(
                    project_id=project_id,
                    code_unit_count=3,
                    test_unit_count=1,
                    skipped_file_count=2,
                )
                response = client.post(
                    "/projects/zip",
                    files={"file": ("repo.zip", b"binary-zip-bytes", "application/zip")},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        assert response.headers["location"] == f"/projects/{project_id}"
        body = response.json()
        assert body == {
            "id": str(project_id),
            "code_unit_count": 3,
            "test_unit_count": 1,
            "skipped_file_count": 2,
        }

    def test_missing_file_field_returns_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            response = client.post("/projects/zip")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422


class TestIngestGithub:
    def test_valid_url_returns_201(self, app: FastAPI, client: TestClient) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        project_id = uuid4()
        try:
            with patch(
                "app.api.routes.projects.ingest_github", new_callable=AsyncMock
            ) as mock_ingest:
                mock_ingest.return_value = IngestionOutcome(
                    project_id=project_id,
                    code_unit_count=5,
                    test_unit_count=2,
                    skipped_file_count=0,
                )
                response = client.post(
                    "/projects/github", json={"github_url": "https://github.com/o/r"}
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        body = response.json()
        assert body == {
            "id": str(project_id),
            "code_unit_count": 5,
            "test_unit_count": 2,
            "skipped_file_count": 0,
        }

    def test_missing_github_url_returns_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            response = client.post("/projects/github", json={})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_non_string_github_url_returns_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            response = client.post("/projects/github", json={"github_url": 123})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422


class TestGetProject:
    def test_found_returns_200_with_counts(
        self, app: FastAPI, client: TestClient
    ) -> None:
        project_id = uuid4()
        fake_project = _FakeProject(project_id)

        async def _session() -> AsyncIterator[_FakeProjectSession]:
            yield _FakeProjectSession(fake_project, code_count=4, test_count=2)

        app.dependency_overrides[get_db_session] = _session
        try:
            response = client.get(f"/projects/{project_id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(project_id)
        assert body["code_unit_count"] == 4
        assert body["test_unit_count"] == 2
        assert body["name"] == "octocat/hello-world"
        assert body["source_repo_url"] == "https://github.com/octocat/hello-world"

    def test_not_found_returns_404(self, app: FastAPI, client: TestClient) -> None:
        async def _session() -> AsyncIterator[_FakeProjectSession]:
            yield _FakeProjectSession(None)

        app.dependency_overrides[get_db_session] = _session
        try:
            response = client.get(f"/projects/{uuid4()}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_malformed_uuid_returns_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            response = client.get("/projects/not-a-uuid")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (ArchiveTooLargeError("too big"), 413),
            (UnsafeArchiveError("unsafe"), 400),
            (InvalidArchiveError("bad archive"), 400),
            (InvalidRepositoryURLError("bad url"), 400),
            (CloneTimeoutError("timed out"), 504),
            (CloneError("clone failed"), 502),
            (ParseError("bad syntax", path=Path(__file__)), 422),
            (AllFilesFailedError(discovered_count=3, skipped_count=3), 422),
            (IngestionError("unmapped subclass"), 500),
        ],
    )
    def test_ingestion_error_maps_to_expected_status(
        self, app: FastAPI, client: TestClient, exc: IngestionError, expected_status: int
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            with patch(
                "app.api.routes.projects.ingest_zip", new_callable=AsyncMock
            ) as mock_ingest:
                mock_ingest.side_effect = exc
                response = client.post(
                    "/projects/zip",
                    files={"file": ("repo.zip", b"bytes", "application/zip")},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == expected_status
        body = response.json()
        assert set(body.keys()) == {"detail"}
        assert isinstance(body["detail"], str)
        assert len(body["detail"]) < 100

    @pytest.mark.parametrize(
        ("pipeline_function", "request_kwargs"),
        [
            (
                "ingest_zip",
                {
                    "method": "post",
                    "url": "/projects/zip",
                    "files": {"file": ("repo.zip", b"bytes", "application/zip")},
                },
            ),
            (
                "ingest_github",
                {
                    "method": "post",
                    "url": "/projects/github",
                    "json": {"github_url": "https://github.com/o/r"},
                },
            ),
        ],
    )
    def test_all_files_failed_error_maps_to_422_on_both_endpoints(
        self,
        app: FastAPI,
        client: TestClient,
        pipeline_function: str,
        request_kwargs: dict[str, Any],
    ) -> None:
        app.dependency_overrides[get_db_session] = _null_session
        try:
            with patch(
                f"app.api.routes.projects.{pipeline_function}", new_callable=AsyncMock
            ) as mock_ingest:
                mock_ingest.side_effect = AllFilesFailedError(
                    discovered_count=4, skipped_count=4
                )
                method = request_kwargs.pop("method")
                url = request_kwargs.pop("url")
                response = getattr(client, method)(url, **request_kwargs)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert set(body.keys()) == {"detail"}
        assert isinstance(body["detail"], str)

    def test_sqlalchemy_error_maps_to_500(
        self, app: FastAPI, client: TestClient
    ) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        app.dependency_overrides[get_db_session] = _null_session
        try:
            with patch(
                "app.api.routes.projects.ingest_zip", new_callable=AsyncMock
            ) as mock_ingest:
                mock_ingest.side_effect = SQLAlchemyError("db exploded internally")
                response = client.post(
                    "/projects/zip",
                    files={"file": ("repo.zip", b"bytes", "application/zip")},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 500
        body = response.json()
        assert body == {"detail": "internal server error"}
        assert "db exploded internally" not in response.text
