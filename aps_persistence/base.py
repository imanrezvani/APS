"""Declarative base for the Phase 10 persistence models.

A dedicated declarative base (rather than reusing anything from the engine)
keeps ORM metadata and the migration target isolated from the domain model.
The APS Engine domain dataclasses never import SQLAlchemy; only this package
does.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all persistence models."""
