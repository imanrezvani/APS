"""Programmatic Alembic helpers (Phase 10 P1).

The migration directory lives at the repository root (``alembic/``) and its
``env.py`` resolves the database URL from the same environment configuration
as the rest of the persistence layer (``DATABASE_URL`` / ``APS_DATABASE_URL``),
so no credentials are ever stored in ``alembic.ini``.

These helpers let tests and embedding code run migrations without the
Alembic CLI:

    from aps_persistence.migrate import upgrade, current
    upgrade()          # alembic upgrade head
    current()          # current revision
"""

from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from aps_persistence.config import resolve_database_url

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_LOCATION = REPO_ROOT / "alembic"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def alembic_config(url: Optional[str] = None) -> Config:
    """Build an Alembic config pointing at this repository's migrations.

    When ``url`` is given it overrides the environment for this run only;
    it is kept in memory and never written to disk.
    """
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", url or resolve_database_url())
    return config


def upgrade(url: Optional[str] = None, revision: str = "head") -> None:
    """Apply migrations up to ``revision`` (default: head)."""
    command.upgrade(alembic_config(url), revision)


def downgrade(url: Optional[str] = None, revision: str = "-1") -> None:
    """Roll migrations back (default: one revision)."""
    command.downgrade(alembic_config(url), revision)


def current(url: Optional[str] = None) -> None:
    """Print the current revision for the configured database."""
    command.current(alembic_config(url), verbose=False)
