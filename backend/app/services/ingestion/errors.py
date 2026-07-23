"""Exceptions raised by the ingestion layer.

Kept small and intent-shaped so the HTTP layer can map each to a specific status
code without inspecting messages. All errors carry a human-readable ``reason``
for logs; the HTTP layer decides whether to expose it verbatim.
"""

from __future__ import annotations

from pathlib import Path


class IngestionError(Exception):
    """Base class for anything the ingestion layer refuses."""


class InvalidArchiveError(IngestionError):
    """The archive is malformed or not a supported format (→ 400)."""


class UnsafeArchiveError(IngestionError):
    """Traversal attempt, symlink, or otherwise unsafe entry (→ 400).

    Distinct from :class:`InvalidArchiveError` because it signals *intent* to
    escape the checkout directory, not just corruption. Never expose the
    ``reason`` field verbatim to end users.
    """


class ArchiveTooLargeError(IngestionError):
    """Uncompressed size or entry count exceeds the configured cap (→ 413)."""


class InvalidRepositoryURLError(IngestionError):
    """The repository URL is malformed, uses an unsupported scheme, targets a
    disallowed host, or embeds credentials (→ 400)."""


class CloneError(IngestionError):
    """The clone operation itself failed (→ 502 / 504 depending on cause).

    Wraps network failures, non-existent repos, private repos (auth required),
    and timeouts into a single type. The ``reason`` field carries the original
    message for logs; the HTTP layer maps the subclass to the right status code.
    """


class CloneTimeoutError(CloneError):
    """A clone exceeded the configured timeout (→ 504)."""


class ParseError(IngestionError):
    """AST parsing of one Python source file failed.

    Wraps read failures (``OSError``, ``UnicodeDecodeError``), syntax errors
    from ``ast.parse``, and the unexpected-``None`` case from
    ``ast.get_source_segment``. ``path`` identifies the offending file so
    orchestration (Step 8) can skip-and-log without re-deriving it from the
    exception message.
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path


class AllFilesFailedError(IngestionError):
    """Every discovered file failed to parse (→ 422).

    Distinct from a per-file :class:`ParseError`, which is skippable: this
    fires only when a non-empty discovery result yields zero successfully
    parsed modules, so there is nothing to persist and no ``Project`` row is
    created.
    """

    def __init__(self, *, discovered_count: int, skipped_count: int) -> None:
        super().__init__(
            f"all {discovered_count} discovered file(s) failed to parse"
        )
        self.discovered_count = discovered_count
        self.skipped_count = skipped_count
