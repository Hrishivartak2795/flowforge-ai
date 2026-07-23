"""The checkout directory abstraction.

A :class:`CheckoutDir` is a temporary, per-ingestion directory on local disk into
which either the ZIP extractor or (next step) the GitHub cloner writes the
repository's files. The parser and every downstream discovery step treats it as
"a path to source files" — they never learn whether the source was a ZIP or a
clone, which is what keeps the parser input-agnostic and lets future inputs
(direct filesystem, tarball) drop in.

Instances are context managers so cleanup is deterministic:

    with CheckoutDir.create(settings.uploads_dir, prefix="proj-") as ck:
        extract_zip(zip_path, ck)
        # ck.root is a real Path here
    # ck.root is gone here
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self


@dataclass(frozen=True)
class CheckoutDir:
    """A materialized directory of source files with deterministic cleanup.

    ``root`` is the absolute path of the temp directory. It exists on disk from
    :meth:`create` until :meth:`cleanup` (or the context exit) is called.
    """

    root: Path

    # ------------------------------------------------------------ construction

    @classmethod
    def create(cls, parent: Path, *, prefix: str = "flowforge-") -> Self:
        """Create a new isolated checkout directory under ``parent``.

        ``parent`` (typically ``settings.uploads_dir``) is created if missing so
        first-run doesn't require an out-of-band ``mkdir``.
        """
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
        return cls(root=root.resolve())

    # ---------------------------------------------------------------- helpers

    def contains(self, candidate: Path) -> bool:
        """Return whether ``candidate`` resolves inside :attr:`root`.

        Used by extractors to enforce zip-slip / traversal safety: any path an
        untrusted archive names must ``resolve()`` to something under ``root``.
        """
        try:
            candidate.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    def cleanup(self) -> None:
        """Remove the directory and everything under it. Idempotent."""
        shutil.rmtree(self.root, ignore_errors=True)

    # -------------------------------------------------------- context manager

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.cleanup()
