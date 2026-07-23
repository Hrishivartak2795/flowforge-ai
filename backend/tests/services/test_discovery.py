"""Tests for :mod:`app.services.ingestion.discovery`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.discovery import (
    _IGNORED_DIR_NAMES,
    FileClassification,
    discover_python_files,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test", log_level="WARNING")  # type: ignore[call-arg]


def _rel_names(result: object) -> list[str]:
    return [f.relative_path.as_posix() for f in result.files]  # type: ignore[attr-defined]


class TestBasicDiscovery:
    def test_discovers_py_files_in_flat_directory(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            (ck.root / "a.py").write_text("x = 1\n")
            (ck.root / "b.py").write_text("y = 2\n")

            result = discover_python_files(ck, settings)

        assert _rel_names(result) == ["a.py", "b.py"]

    def test_descends_into_nested_subdirectories(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            nested = ck.root / "pkg" / "sub"
            nested.mkdir(parents=True)
            (nested / "mod.py").write_text("z = 3\n")

            result = discover_python_files(ck, settings)

        assert _rel_names(result) == ["pkg/sub/mod.py"]

    def test_ignores_non_py_files_silently(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            (ck.root / "notes.txt").write_text("hi\n")
            (ck.root / "README.md").write_text("# readme\n")
            (ck.root / "compiled.pyc").write_bytes(b"\x00")
            (ck.root / "real.py").write_text("a = 1\n")

            result = discover_python_files(ck, settings)

        assert _rel_names(result) == ["real.py"]

    def test_empty_checkout_returns_empty_result(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            result = discover_python_files(ck, settings)

        assert result.files == ()
        assert result.skipped_oversized_count == 0


class TestIgnoreList:
    @pytest.mark.parametrize("ignored_dir", sorted(_IGNORED_DIR_NAMES))
    def test_skips_each_ignored_directory_at_root(
        self, tmp_path: Path, settings: Settings, ignored_dir: str
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            bad = ck.root / ignored_dir
            bad.mkdir()
            (bad / "hidden.py").write_text("secret = 1\n")
            (ck.root / "visible.py").write_text("ok = 1\n")

            result = discover_python_files(ck, settings)

        assert _rel_names(result) == ["visible.py"]

    def test_ignore_list_applies_at_any_depth(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            deep_ignored = ck.root / "pkg" / "node_modules"
            deep_ignored.mkdir(parents=True)
            (deep_ignored / "hidden.py").write_text("secret = 1\n")
            (ck.root / "pkg" / "visible.py").write_text("ok = 1\n")

            result = discover_python_files(ck, settings)

        assert _rel_names(result) == ["pkg/visible.py"]


class TestSymlinks:
    def test_does_not_follow_symlinked_directory(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "escaped.py").write_text("leak = 1\n")

        with CheckoutDir.create(tmp_path / "u") as ck:
            link = ck.root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                pytest.skip("symlink creation not permitted in this environment")

            result = discover_python_files(ck, settings)

        assert result.files == ()

    def test_does_not_follow_symlinked_file(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        outside = tmp_path / "outside.py"
        outside.write_text("leak = 1\n")

        with CheckoutDir.create(tmp_path / "u") as ck:
            link = ck.root / "linked.py"
            try:
                link.symlink_to(outside)
            except OSError:
                pytest.skip("symlink creation not permitted in this environment")

            result = discover_python_files(ck, settings)

        assert result.files == ()


class TestSizeCap:
    def test_skips_oversized_file_and_counts_it(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        small_settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="test",
            log_level="WARNING",
            max_file_bytes=10,
        )
        with CheckoutDir.create(tmp_path / "u") as ck:
            (ck.root / "big.py").write_text("x" * 100)
            (ck.root / "small.py").write_text("x = 1\n")

            result = discover_python_files(ck, small_settings)

        assert _rel_names(result) == ["small.py"]
        assert result.skipped_oversized_count == 1


class TestClassification:
    def test_classifies_plain_module_as_code(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            (ck.root / "service.py").write_text("x = 1\n")

            result = discover_python_files(ck, settings)

        assert result.files[0].classification == FileClassification.CODE

    def test_classifies_file_under_tests_dir_as_test(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            tests_dir = ck.root / "tests"
            tests_dir.mkdir()
            (tests_dir / "helpers.py").write_text("x = 1\n")

            result = discover_python_files(ck, settings)

        assert result.files[0].classification == FileClassification.TEST

    def test_classifies_test_prefix_filename_as_test_anywhere(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            pkg = ck.root / "pkg"
            pkg.mkdir()
            (pkg / "test_service.py").write_text("x = 1\n")

            result = discover_python_files(ck, settings)

        assert result.files[0].classification == FileClassification.TEST

    def test_classifies_test_suffix_filename_as_test_anywhere(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            pkg = ck.root / "pkg"
            pkg.mkdir()
            (pkg / "service_test.py").write_text("x = 1\n")

            result = discover_python_files(ck, settings)

        assert result.files[0].classification == FileClassification.TEST


class TestDeterministicOrdering:
    def test_two_runs_over_identical_input_match(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        with CheckoutDir.create(tmp_path / "u") as ck:
            (ck.root / "z.py").write_text("z = 1\n")
            (ck.root / "a.py").write_text("a = 1\n")
            nested = ck.root / "m"
            nested.mkdir()
            (nested / "b.py").write_text("b = 1\n")

            first = discover_python_files(ck, settings)
            second = discover_python_files(ck, settings)

        assert first.files == second.files
        assert _rel_names(first) == ["a.py", "m/b.py", "z.py"]
