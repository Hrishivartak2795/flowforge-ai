"""Declarative base for all ORM models.

A single :class:`Base` owns the shared ``MetaData``. The naming convention makes
every index/constraint name deterministic and human-readable, which keeps
Alembic autogenerate diffs stable across machines and milestones (no random
auto-named constraints that churn between runs).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic names for indexes/constraints (ix_/uq_/ck_/fk_/pk_).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base. All models inherit from this."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
