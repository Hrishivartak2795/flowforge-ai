"""Repository file discovery — walk a :class:`CheckoutDir`, classify, bound.

Turns a materialized checkout (from the ZIP extractor or the GitHub cloner)
into a deterministic, bounded list of Python source files the parser will
consume next. Deterministic, DB-free, network-free — no ``ast``, no repo code
execution.

Defenses:

- **Ignore list.** Well-known dependency/VCS/cache directories are skipped as
  whole subtrees (never descended into), matching the frozen M2 design.
- **No symlink traversal.** ``os.walk(followlinks=False)`` — a malicious or
  merely inconvenient symlink can never pull discovery outside the checkout
  or into a cycle.
- **Per-file size cap.** ``settings.max_file_bytes`` bounds what later stages
  (AST parsing, embedding) will ever see; oversized files are skipped and
  logged, never fatal.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.core.config import Settings
from app.services.ingestion.checkout import CheckoutDir

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ ignore list

_IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)


class FileClassification(StrEnum):
    """Deterministic path-based split between implementation and test code."""

    CODE = "code"
    TEST = "test"


@dataclass(frozen=True)
class DiscoveredFile:
    """One discovered Python source file, classified and located."""

    absolute_path: Path
    relative_path: Path
    classification: FileClassification


@dataclass(frozen=True)
class DiscoveryResult:
    """The bounded, sorted output of a discovery pass over one checkout."""

    files: tuple[DiscoveredFile, ...]
    skipped_oversized_count: int


# ---------------------------------------------------------------- classification


def _classify(relative_path: Path) -> FileClassification:
    """``test`` if under a ``tests`` segment or matches the test filename glob."""
    if "tests" in relative_path.parts[:-1]:
        return FileClassification.TEST
    name = relative_path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return FileClassification.TEST
    return FileClassification.CODE


# -------------------------------------------------------------------- discovery


def discover_python_files(
    checkout: CheckoutDir, settings: Settings
) -> DiscoveryResult:
    """Walk ``checkout.root`` and return its classified, bounded ``.py`` files.

    Symlinked directories and files are never followed/read. Ignored directory
    names are pruned in-place so :func:`os.walk` never descends into them.
    Oversized files are skipped-and-logged; the run continues.
    """
    root = checkout.root
    discovered: list[DiscoveredFile] = []
    skipped_oversized_count = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _IGNORED_DIR_NAMES
            and not (Path(dirpath) / d).is_symlink()
        ]

        current_dir = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(".py"):
                continue

            absolute_path = current_dir / filename
            if absolute_path.is_symlink():
                continue

            relative_path = absolute_path.relative_to(root)

            size = absolute_path.stat().st_size
            if size > settings.max_file_bytes:
                skipped_oversized_count += 1
                logger.warning(
                    "discovery.file_skipped_oversized",
                    extra={
                        "relative_path": relative_path.as_posix(),
                        "size_bytes": size,
                        "max_file_bytes": settings.max_file_bytes,
                    },
                )
                continue

            discovered.append(
                DiscoveredFile(
                    absolute_path=absolute_path.resolve(),
                    relative_path=relative_path,
                    classification=_classify(relative_path),
                )
            )

    discovered.sort(key=lambda f: f.relative_path.as_posix())

    return DiscoveryResult(
        files=tuple(discovered),
        skipped_oversized_count=skipped_oversized_count,
    )
