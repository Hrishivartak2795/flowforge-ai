"""Tests for :mod:`app.services.ingestion.checkout`."""

from __future__ import annotations

from pathlib import Path

from app.services.ingestion.checkout import CheckoutDir


def test_create_and_cleanup(tmp_path: Path) -> None:
    ck = CheckoutDir.create(tmp_path / "uploads")
    assert ck.root.exists()
    assert ck.root.parent == (tmp_path / "uploads").resolve()

    (ck.root / "hello.py").write_text("print('hi')\n")
    ck.cleanup()
    assert not ck.root.exists()


def test_context_manager_cleans_up_on_exit(tmp_path: Path) -> None:
    with CheckoutDir.create(tmp_path / "uploads") as ck:
        (ck.root / "a.py").write_text("x = 1\n")
        root = ck.root
        assert root.exists()
    assert not root.exists()


def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    ck = CheckoutDir.create(tmp_path / "uploads")
    ck.cleanup()
    ck.cleanup()  # no error


def test_contains_accepts_paths_inside_root(tmp_path: Path) -> None:
    with CheckoutDir.create(tmp_path / "u") as ck:
        assert ck.contains(ck.root / "a" / "b.py")
        assert ck.contains(ck.root)  # root itself is "inside"


def test_contains_rejects_paths_outside_root(tmp_path: Path) -> None:
    with CheckoutDir.create(tmp_path / "u") as ck:
        assert not ck.contains(tmp_path / "elsewhere")
        # A ``..`` walk that would escape must be rejected:
        assert not ck.contains(ck.root / ".." / ".." / "etc" / "passwd")
