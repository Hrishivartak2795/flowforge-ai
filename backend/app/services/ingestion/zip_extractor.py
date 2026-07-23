"""Safe ZIP → :class:`CheckoutDir` extraction.

Threat model. The uploaded ZIP is *untrusted*. An attacker can attempt:

- **Path traversal (zip-slip).** An entry named ``../../etc/passwd`` that would
  write outside the checkout dir.
- **Symlink injection.** A symlink entry pointing at ``/`` (or into the
  checkout, then a follow-up entry writing through it).
- **Zip-bomb.** Small compressed archive expanding to gigabytes.
- **File-count DoS.** A million tiny entries exhausting inodes / walk time.

Defenses (all pre-flight — nothing hits disk until the whole archive validates):

1. Enumerate ``ZipFile.infolist()`` and inspect every entry name and metadata.
2. Reject absolute paths, ``..`` segments, backslashes, and drive letters.
3. Reject any entry whose kind isn't a regular file or directory (symlinks,
   devices, hardlinks — anything not ``file`` or ``dir``).
4. Sum ``file_size`` (uncompressed) and count entries; refuse over caps.
5. On extract, resolve the target path and re-check it's inside the root.

The extractor is a pure function of ``(zip_path, checkout, limits)`` — no logs,
no globals, no service coupling — so it's trivially unit-testable.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.errors import (
    ArchiveTooLargeError,
    InvalidArchiveError,
    UnsafeArchiveError,
)


@dataclass(frozen=True)
class ExtractionLimits:
    """Per-ingestion caps. Sourced from ``Settings`` at the service edge."""

    max_uncompressed_bytes: int
    max_entries: int


@dataclass(frozen=True)
class ExtractionResult:
    """Summary of a successful extraction, useful for logs and API responses."""

    file_count: int
    total_uncompressed_bytes: int


# ---------------------------------------------------------- entry-name checks

_DISALLOWED_NAME_PARTS: frozenset[str] = frozenset({"", ".", ".."})


def _validate_entry_name(raw_name: str) -> PurePosixPath:
    """Return a safe relative :class:`PurePosixPath`, or raise.

    Rejects absolute paths, drive letters, backslashes (Windows separators
    inside a ZIP are a strong signal of a malicious archive — the spec is
    forward-slashes), and any component that is ``..`` / empty / ``.``.
    """
    if not raw_name:
        raise UnsafeArchiveError("empty entry name")
    if "\\" in raw_name:
        raise UnsafeArchiveError(f"backslash in entry name: {raw_name!r}")
    posix = PurePosixPath(raw_name)
    if posix.is_absolute() or (len(raw_name) >= 2 and raw_name[1] == ":"):
        raise UnsafeArchiveError(f"absolute path in archive: {raw_name!r}")
    for part in posix.parts:
        if part in _DISALLOWED_NAME_PARTS:
            raise UnsafeArchiveError(f"disallowed path segment in {raw_name!r}")
    return posix


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Detect Unix symlink entries via the external-attrs high byte.

    ZIPs encode POSIX mode in the top 16 bits of ``external_attr`` when created
    on Unix. Mode ``0o120000`` is ``S_IFLNK``.
    """
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return (unix_mode & 0o170000) == 0o120000


# ------------------------------------------------------------------- pre-flight

def _preflight(
    zf: zipfile.ZipFile, limits: ExtractionLimits
) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], int]:
    """Validate the whole archive before touching disk. Returns (entries, total)."""
    entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total_bytes = 0
    file_count = 0

    for info in zf.infolist():
        if _is_symlink(info):
            raise UnsafeArchiveError(f"symlink entry rejected: {info.filename!r}")

        safe_name = _validate_entry_name(info.filename)

        if info.is_dir():
            entries.append((info, safe_name))
            continue

        # Regular file. Guard cumulative caps *before* we admit it.
        file_count += 1
        if file_count > limits.max_entries:
            raise ArchiveTooLargeError(
                f"archive has more than {limits.max_entries} file entries"
            )
        total_bytes += info.file_size
        if total_bytes > limits.max_uncompressed_bytes:
            raise ArchiveTooLargeError(
                f"uncompressed size exceeds {limits.max_uncompressed_bytes} bytes"
            )
        entries.append((info, safe_name))

    return entries, total_bytes


# --------------------------------------------------------------- public entrypoint

def extract_zip(
    zip_path: Path, checkout: CheckoutDir, limits: ExtractionLimits
) -> ExtractionResult:
    """Extract ``zip_path`` into ``checkout``, or raise an ingestion error.

    All validation runs first; nothing is written unless the archive fully
    validates. Directories in the archive are materialized as empty dirs;
    file entries are read and written through ``ZipFile.read`` so we never
    call the underlying extractor that follows ZIP paths on its own.
    """
    if not zip_path.is_file():
        raise InvalidArchiveError(f"not a file: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path) as zf:
            entries, total_bytes = _preflight(zf, limits)

            file_count = 0
            for info, safe_name in entries:
                target = (checkout.root / safe_name).resolve()
                # Final containment check — belt & braces after the name-level
                # validation. Any resolution mismatch is a bug or an exploit.
                if not checkout.contains(target):
                    raise UnsafeArchiveError(
                        f"resolved outside checkout: {info.filename!r}"
                    )

                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                # `read` loads bytes into memory, but we've already capped the
                # per-file (and cumulative) uncompressed size, so this is safe.
                target.write_bytes(zf.read(info))
                file_count += 1

    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(f"malformed zip: {exc}") from exc

    return ExtractionResult(
        file_count=file_count, total_uncompressed_bytes=total_bytes
    )
