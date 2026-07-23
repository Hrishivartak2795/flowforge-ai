"""Tests for :mod:`app.services.ingestion.git_cloner`.

Every test in the normal suite runs without internet access. Git operations are
mocked via ``monkeypatch`` on ``git.Repo.clone_from``. A single integration
test at the bottom clones a real public GitHub repo and is gated behind
``--run-network`` / the ``network`` pytest marker — it will never run in CI
or plain ``pytest`` unless explicitly opted in.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import git
import pytest

from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.errors import (
    CloneError,
    CloneTimeoutError,
    InvalidRepositoryURLError,
)
from app.services.ingestion.git_cloner import (
    CloneConfig,
    clone_repo,
    validate_repo_url,
)

# ============================================================ URL validation


class TestValidateRepoUrl:
    """Pure validation — no Git, no network, no mocking needed."""

    def test_accepts_valid_github_https_url(self) -> None:
        url = "https://github.com/pallets/flask"
        assert validate_repo_url(url) == url

    def test_accepts_www_github(self) -> None:
        assert validate_repo_url("https://www.github.com/pallets/flask")

    def test_accepts_url_with_dot_git_suffix(self) -> None:
        url = "https://github.com/pallets/flask.git"
        assert validate_repo_url(url) == url

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(InvalidRepositoryURLError):
            validate_repo_url("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(InvalidRepositoryURLError):
            validate_repo_url("   ")

    def test_rejects_http_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="unsupported scheme"):
            validate_repo_url("http://github.com/owner/repo")

    def test_rejects_ssh_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="unsupported scheme"):
            validate_repo_url("ssh://git@github.com/owner/repo")

    def test_rejects_git_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="unsupported scheme"):
            validate_repo_url("git://github.com/owner/repo")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="unsupported scheme"):
            validate_repo_url("file:///etc/passwd")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="unsupported scheme"):
            validate_repo_url("ftp://github.com/owner/repo")

    def test_rejects_missing_scheme(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="missing URL scheme"):
            validate_repo_url("github.com/owner/repo")

    def test_rejects_non_github_host(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="not in the allow-list"):
            validate_repo_url("https://gitlab.com/owner/repo")

    def test_rejects_bitbucket_host(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="not in the allow-list"):
            validate_repo_url("https://bitbucket.org/owner/repo")

    def test_rejects_ssrf_metadata_endpoint(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="not in the allow-list"):
            validate_repo_url("https://169.254.169.254/latest/meta-data")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="not in the allow-list"):
            validate_repo_url("https://localhost/owner/repo")

    def test_rejects_internal_host(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="not in the allow-list"):
            validate_repo_url("https://internal.corp.example.com/owner/repo")

    def test_rejects_embedded_username(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="credentials"):
            validate_repo_url("https://user@github.com/owner/repo")

    def test_rejects_embedded_username_and_password(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="credentials"):
            validate_repo_url("https://user:pass@github.com/owner/repo")

    def test_rejects_local_absolute_path(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="local filesystem"):
            validate_repo_url("/home/user/repo")

    def test_rejects_local_relative_path(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="local filesystem"):
            validate_repo_url("./local-repo")

    def test_rejects_windows_path(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="local filesystem"):
            validate_repo_url("C:\\Users\\me\\repo")

    def test_rejects_path_without_owner_repo(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="owner/repo"):
            validate_repo_url("https://github.com/lonely-owner")

    def test_rejects_github_root_only(self) -> None:
        with pytest.raises(InvalidRepositoryURLError, match="owner/repo"):
            validate_repo_url("https://github.com/")

    def test_strips_whitespace_before_validating(self) -> None:
        url = "  https://github.com/owner/repo  "
        assert validate_repo_url(url) == url.strip()


# ============================================================ clone_repo


class TestCloneRepo:
    """Clone behavior tests — Git is mocked, no network access."""

    def test_successful_clone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_clone = MagicMock()
        monkeypatch.setattr(git.Repo, "clone_from", mock_clone)

        with CheckoutDir.create(tmp_path / "u") as ck:
            result = clone_repo(
                "https://github.com/owner/repo", ck, CloneConfig()
            )

        assert result.url == "https://github.com/owner/repo"
        assert result.cloned_to == str(ck.root)
        mock_clone.assert_called_once_with(
            "https://github.com/owner/repo",
            to_path=str(ck.root),
            depth=1,
            single_branch=True,
            kill_after_timeout=120,
        )

    def test_clone_passes_custom_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_clone = MagicMock()
        monkeypatch.setattr(git.Repo, "clone_from", mock_clone)

        with CheckoutDir.create(tmp_path / "u") as ck:
            clone_repo(
                "https://github.com/owner/repo",
                ck,
                CloneConfig(clone_timeout_seconds=30),
            )

        assert mock_clone.call_args.kwargs["kill_after_timeout"] == 30

    def test_clone_validates_url_before_cloning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_clone = MagicMock()
        monkeypatch.setattr(git.Repo, "clone_from", mock_clone)

        with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(
            InvalidRepositoryURLError
        ):
            clone_repo("https://evil.com/owner/repo", ck)

        mock_clone.assert_not_called()  # never reached the network

    def test_clone_failure_raises_clone_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*_args: object, **_kwargs: object) -> None:
            raise git.GitCommandError("clone", 128, stderr="repository not found")

        monkeypatch.setattr(git.Repo, "clone_from", _fail)

        with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(CloneError):
            clone_repo("https://github.com/owner/nonexistent", ck)

    def test_private_repo_raises_clone_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _auth_fail(*_args: object, **_kwargs: object) -> None:
            raise git.GitCommandError(
                "clone", 128, stderr="could not read from remote repository"
            )

        monkeypatch.setattr(git.Repo, "clone_from", _auth_fail)

        with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(CloneError):
            clone_repo("https://github.com/owner/private-repo", ck)

    def test_timeout_raises_clone_timeout_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _timeout(*_args: object, **_kwargs: object) -> None:
            raise git.GitCommandError("clone", -9, stderr="timeout: killed")

        monkeypatch.setattr(git.Repo, "clone_from", _timeout)

        with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(
            CloneTimeoutError
        ):
            clone_repo("https://github.com/owner/huge-repo", ck)

    def test_timeout_detected_via_status_minus_9(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GitPython uses SIGKILL (exit status -9) for ``kill_after_timeout``."""

        def _sigkill(*_args: object, **_kwargs: object) -> None:
            raise git.GitCommandError("clone", -9, stderr="")

        monkeypatch.setattr(git.Repo, "clone_from", _sigkill)

        with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(
            CloneTimeoutError
        ):
            clone_repo("https://github.com/owner/repo", ck)

    def test_checkout_dir_survives_clone_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The caller owns cleanup — a failed clone should not delete the dir."""

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise git.GitCommandError("clone", 128, stderr="network unreachable")

        monkeypatch.setattr(git.Repo, "clone_from", _fail)

        with CheckoutDir.create(tmp_path / "u") as ck:
            with pytest.raises(CloneError):
                clone_repo("https://github.com/owner/repo", ck)
            # CheckoutDir must still exist — the context manager cleans up,
            # not the cloner.
            assert ck.root.exists()

    def test_default_config_used_when_none_passed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_clone = MagicMock()
        monkeypatch.setattr(git.Repo, "clone_from", mock_clone)

        with CheckoutDir.create(tmp_path / "u") as ck:
            clone_repo("https://github.com/owner/repo", ck)

        assert mock_clone.call_args.kwargs["kill_after_timeout"] == 120


# ============================================================ integration test
# Requires real internet access. Gated behind a custom marker so ``pytest``
# and CI never run it by default.
#
# Run manually:  uv run pytest -m network --run-network


@pytest.mark.network
def test_real_clone_from_github(tmp_path: Path) -> None:
    """Clone a tiny, well-known public repo and verify files landed."""
    with CheckoutDir.create(tmp_path / "u") as ck:
        result = clone_repo(
            "https://github.com/octocat/Hello-World",
            ck,
            CloneConfig(clone_timeout_seconds=60),
        )
        assert result.url == "https://github.com/octocat/Hello-World"
        assert ck.root.exists()
        assert any(ck.root.iterdir())  # at least one file/dir
        readme = ck.root / "README"
        assert readme.is_file(), f"Expected README in {list(ck.root.iterdir())}"
