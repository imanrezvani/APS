"""Declarative base for the Phase 10 persistence models.

A dedicated declarative base (rather than reusing anything from the engine)
keeps ORM metadata and the migration target isolated from the domain model.
The APS Engine domain dataclasses never import SQLAlchemy; only this package
does.

An explicit naming convention keeps constraint/index names stable and makes
Alembic autogenerate diffs deterministic.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all persistence models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
