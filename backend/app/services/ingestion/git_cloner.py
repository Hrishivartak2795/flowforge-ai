"""GitHub repository → :class:`CheckoutDir` cloner.

Threat model. The repository URL is *untrusted user input*. An attacker can
attempt:

- **SSRF.** A URL targeting internal hosts, cloud metadata endpoints
  (``169.254.169.254``), or non-HTTP services via exotic schemes.
- **Credential leakage.** A URL embedding ``user:pass@`` that would be logged
  or sent to an attacker-controlled host.
- **Local file access.** ``file:///etc/passwd`` or bare filesystem paths.
- **Resource exhaustion.** Cloning a multi-GB monorepo.

Defenses:

1. **URL parsing + validation** before any network I/O: scheme allow-list
   (``https`` only), host allow-list (``github.com`` only for MVP), reject
   embedded credentials, reject non-URL paths.
2. **Shallow clone** (``depth=1``) — minimises bandwidth, storage, and exposure
   to Git-protocol exploits in history objects.
3. **Timeout** — a hard cap on the clone operation.
4. **Checkout-dir isolation** — the clone lands inside a :class:`CheckoutDir`
   that is cleaned up deterministically on success or failure.

The cloner is a pure function of ``(url, checkout, config)`` — no globals, no
service coupling — so it's testable with a mocked ``git.Repo.clone_from``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import git

from app.services.ingestion.checkout import CheckoutDir
from app.services.ingestion.errors import (
    CloneError,
    CloneTimeoutError,
    InvalidRepositoryURLError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- configuration

# MVP: only public GitHub repos over HTTPS. Extend the allow-list when the
# design calls for GitLab/Bitbucket — but keep the *structure* (explicit
# allow-list, not a block-list) so unknown hosts are rejected by default.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})
_ALLOWED_HOSTS: frozenset[str] = frozenset({"github.com", "www.github.com"})


@dataclass(frozen=True)
class CloneConfig:
    """Per-clone parameters. Sourced from ``Settings`` at the service edge."""

    clone_timeout_seconds: int = 120


# ---------------------------------------------------------------- URL validation


def validate_repo_url(raw_url: str) -> str:
    """Validate and return a safe clone URL, or raise.

    Returns the normalised URL string on success. All checks run before any
    network I/O.
    """
    if not raw_url or not raw_url.strip():
        raise InvalidRepositoryURLError("empty repository URL")

    raw_url = raw_url.strip()

    # Reject bare filesystem paths early (``/foo``, ``C:\\foo``, ``./foo``).
    if raw_url.startswith(("/", ".", "\\")):
        raise InvalidRepositoryURLError(
            f"local filesystem path not allowed: {raw_url!r}"
        )
    # Windows drive letters (``C:\...`` or ``C:/...``).
    if len(raw_url) >= 2 and raw_url[1] == ":":
        raise InvalidRepositoryURLError(
            f"local filesystem path not allowed: {raw_url!r}"
        )

    try:
        parsed = urlparse(raw_url)
    except ValueError as exc:
        raise InvalidRepositoryURLError(
            f"malformed URL: {raw_url!r}"
        ) from exc

    # ── scheme ──
    if not parsed.scheme:
        raise InvalidRepositoryURLError(
            f"missing URL scheme (expected https://): {raw_url!r}"
        )
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidRepositoryURLError(
            f"unsupported scheme {parsed.scheme!r} (only HTTPS allowed)"
        )

    # ── host ──
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidRepositoryURLError(f"missing host in URL: {raw_url!r}")
    if host not in _ALLOWED_HOSTS:
        raise InvalidRepositoryURLError(
            f"host {host!r} is not in the allow-list "
            f"(allowed: {', '.join(sorted(_ALLOWED_HOSTS))})"
        )

    # ── credentials ──
    if parsed.username or parsed.password:
        raise InvalidRepositoryURLError(
            "embedded credentials in URL are not allowed"
        )

    # ── path sanity ──
    # A valid GitHub repo URL has at least ``/owner/repo``.
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 2:
        raise InvalidRepositoryURLError(
            f"URL path must contain at least owner/repo: {raw_url!r}"
        )

    return raw_url


# --------------------------------------------------------------- clone

@dataclass(frozen=True)
class CloneResult:
    """Summary of a successful clone, useful for logs and API responses."""

    url: str
    cloned_to: str  # stringified path, safe for JSON


def clone_repo(
    url: str,
    checkout: CheckoutDir,
    config: CloneConfig | None = None,
) -> CloneResult:
    """Clone ``url`` into ``checkout``, or raise an ingestion error.

    Validates the URL first (no network I/O until it passes). The clone is
    shallow (``depth=1``, single branch) to minimise bandwidth and disk.
    """
    config = config or CloneConfig()
    validated_url = validate_repo_url(url)

    # GitPython's clone_from shells out to ``git clone``. We pass
    # ``kill_after_timeout`` to cap wall-clock time. ``depth=1`` +
    # ``single_branch=True`` produce a minimal checkout.
    try:
        logger.info(
            "clone.start",
            extra={"url": validated_url, "timeout": config.clone_timeout_seconds},
        )
        git.Repo.clone_from(
            validated_url,
            to_path=str(checkout.root),
            depth=1,
            single_branch=True,
            kill_after_timeout=config.clone_timeout_seconds,
        )
        logger.info(
            "clone.complete",
            extra={"url": validated_url, "path": str(checkout.root)},
        )
    except git.GitCommandError as exc:
        # GitPython raises GitCommandError for everything: bad URL, auth
        # required, network unreachable, timeout (via SIGKILL). Distinguish
        # timeout by checking the kill flag in stderr/status.
        stderr = str(exc.stderr or "").lower()
        if "timeout" in stderr or exc.status == -9:
            raise CloneTimeoutError(
                f"clone timed out after {config.clone_timeout_seconds}s"
            ) from exc
        raise CloneError(
            f"clone failed for {validated_url!r}: {exc.stderr or exc}"
        ) from exc

    return CloneResult(url=validated_url, cloned_to=str(checkout.root))
