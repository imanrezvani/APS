"""Database configuration (Phase 10 P1).

All configuration comes from environment variables; nothing is hard-coded and
no ``.env`` file is needed (or committed). A ``.env.example`` documents the
variables for local development.

Environment variables
---------------------
``DATABASE_URL`` (or ``APS_DATABASE_URL``)
    SQLAlchemy database URL, e.g.
    ``postgresql+psycopg://user:password@host:5432/dbname``. Required when a
    database connection is actually needed; importing this module never
    touches the environment beyond reading values on demand, so
    engine-only/CLI workflows keep working without a database.
``APS_DB_POOL_SIZE``
    Connection pool size (default 5).
``APS_DB_MAX_OVERFLOW``
    Pool overflow (default 10).
``APS_DB_POOL_TIMEOUT``
    Seconds to wait for a pooled connection (default 30).
``APS_DB_POOL_RECYCLE``
    Recycle connections after this many seconds (default 1800).
``APS_DB_ECHO``
    ``1``/``true`` to echo SQL (default false).
``APS_TEST_DATABASE_URL``
    Test-only override used by the persistence test-suite; never used by
    production code paths.
"""

import os
from dataclasses import dataclass
from typing import Optional


class DatabaseConfigurationError(RuntimeError):
    """Raised when a required database setting is missing or invalid."""


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(
            f"{name} must be an integer, got {raw!r}"
        ) from exc


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_database_url(url: Optional[str] = None) -> str:
    """Return the configured database URL or raise.

    ``url`` wins when given (used by tests and programmatic embedding);
    otherwise ``DATABASE_URL`` / ``APS_DATABASE_URL`` are consulted. The URL
    must be a SQLAlchemy URL; PostgreSQL URLs are expected by Phase 10 but
    the layer does not reject other backends outright.
    """
    value = url or _first_env("DATABASE_URL", "APS_DATABASE_URL")
    if not value:
        raise DatabaseConfigurationError(
            "no database URL configured: set DATABASE_URL (or "
            "APS_DATABASE_URL) to a SQLAlchemy URL such as "
            "'postgresql+psycopg://user:password@host:5432/dbname'"
        )
    if "://" not in value:
        raise DatabaseConfigurationError(
            "database URL must be a SQLAlchemy URL (missing scheme '://'): "
            f"{value!r}"
        )
    return value


def resolve_test_database_url() -> Optional[str]:
    """Return ``APS_TEST_DATABASE_URL`` when set, else None."""
    return _first_env("APS_TEST_DATABASE_URL")


@dataclass(frozen=True)
class DatabaseSettings:
    """Resolved database configuration (no credentials are logged/echoed)."""

    url: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    echo: bool = False

    def engine_kwargs(self) -> dict:
        """Keyword arguments for :func:`sqlalchemy.create_engine`."""
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "pool_pre_ping": True,
            "echo": self.echo,
            "future": True,
        }


def settings_from_env(url: Optional[str] = None) -> DatabaseSettings:
    """Build :class:`DatabaseSettings` from the environment.

    Raises :class:`DatabaseConfigurationError` when no URL is configured.
    Importing/calling this never connects to the database.
    """
    return DatabaseSettings(
        url=resolve_database_url(url),
        pool_size=_int_env("APS_DB_POOL_SIZE", 5),
        max_overflow=_int_env("APS_DB_MAX_OVERFLOW", 10),
        pool_timeout=_int_env("APS_DB_POOL_TIMEOUT", 30),
        pool_recycle=_int_env("APS_DB_POOL_RECYCLE", 1800),
        echo=_bool_env("APS_DB_ECHO", False),
    )
