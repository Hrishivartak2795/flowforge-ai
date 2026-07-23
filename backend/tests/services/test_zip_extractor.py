"""Tests for :mod:`app.services.ingestion.zip_extractor`.

Rather than mocking, each test constructs a real ``.zip`` that exercises a
specific defense (traversal, symlink, size cap, entry-count cap, malformed).
This keeps the test *about the actual bytes* the extractor sees.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.errors import (
    ArchiveTooLargeError,
    InvalidArchiveError,
    UnsafeArchiveError,
)
from app.services.ingestion.zip_extractor import ExtractionLimits, extract_zip

DEFAULT_LIMITS = ExtractionLimits(
    max_uncompressed_bytes=10 * 1024 * 1024, max_entries=1_000
)


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    """Create a well-formed ZIP with the given ``{name: bytes}`` payloads."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


# ------------------------------------------------------------------ happy path


def test_extracts_files_and_preserves_structure(tmp_path: Path) -> None:
    zpath = tmp_path / "repo.zip"
    _write_zip(
        zpath,
        {
            "repo/pkg/__init__.py": b"",
            "repo/pkg/app.py": b"def main():\n    return 1\n",
            "repo/README.md": b"# repo\n",
        },
    )

    with CheckoutDir.create(tmp_path / "u") as ck:
        result = extract_zip(zpath, ck, DEFAULT_LIMITS)

        assert result.file_count == 3
        assert (ck.root / "repo" / "pkg" / "app.py").read_text().startswith("def main")
        assert (ck.root / "repo" / "README.md").is_file()
        assert result.total_uncompressed_bytes > 0


# --------------------------------------------------------- traversal / zip-slip


def test_rejects_dotdot_traversal(tmp_path: Path) -> None:
    zpath = tmp_path / "evil.zip"
    _write_zip(zpath, {"../escaped.py": b"pwned"})

    with CheckoutDir.create(tmp_path / "u") as ck:
        with pytest.raises(UnsafeArchiveError):
            extract_zip(zpath, ck, DEFAULT_LIMITS)
        assert not (tmp_path / "escaped.py").exists()


def test_rejects_absolute_path_entry(tmp_path: Path) -> None:
    zpath = tmp_path / "abs.zip"
    _write_zip(zpath, {"/etc/passwd": b"root:x:0:0::/:/bin/sh\n"})

    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(UnsafeArchiveError):
        extract_zip(zpath, ck, DEFAULT_LIMITS)


def test_rejects_backslash_entry(tmp_path: Path) -> None:
    zpath = tmp_path / "bs.zip"
    _write_zip(zpath, {"repo\\..\\evil.py": b"x"})

    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(UnsafeArchiveError):
        extract_zip(zpath, ck, DEFAULT_LIMITS)


# ------------------------------------------------------------------- symlinks


def test_rejects_symlink_entry(tmp_path: Path) -> None:
    zpath = tmp_path / "sym.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        info = zipfile.ZipInfo("link_to_root")
        # Set the Unix symlink mode in the external attributes high bits.
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, b"/")

    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(UnsafeArchiveError):
        extract_zip(zpath, ck, DEFAULT_LIMITS)


# ------------------------------------------------------------- capacity limits


def test_rejects_archive_over_uncompressed_size_cap(tmp_path: Path) -> None:
    zpath = tmp_path / "big.zip"
    _write_zip(zpath, {"big.py": b"x" * 5000})

    tiny = ExtractionLimits(max_uncompressed_bytes=1000, max_entries=10)
    with CheckoutDir.create(tmp_path / "u") as ck:
        with pytest.raises(ArchiveTooLargeError):
            extract_zip(zpath, ck, tiny)
        # Pre-flight rejects — nothing should have been written.
        assert list(ck.root.iterdir()) == []


def test_rejects_archive_over_entry_count_cap(tmp_path: Path) -> None:
    zpath = tmp_path / "many.zip"
    _write_zip(zpath, {f"f{i}.py": b"x" for i in range(20)})

    fewer = ExtractionLimits(max_uncompressed_bytes=10_000, max_entries=5)
    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(ArchiveTooLargeError):
        extract_zip(zpath, ck, fewer)


# -------------------------------------------------------------- malformed input


def test_rejects_non_zip_file(tmp_path: Path) -> None:
    plain = tmp_path / "not-a.zip"
    plain.write_text("hello, world\n")

    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(InvalidArchiveError):
        extract_zip(plain, ck, DEFAULT_LIMITS)


def test_rejects_missing_path(tmp_path: Path) -> None:
    with CheckoutDir.create(tmp_path / "u") as ck, pytest.raises(InvalidArchiveError):
        extract_zip(tmp_path / "nope.zip", ck, DEFAULT_LIMITS)
