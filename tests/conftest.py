"""Shared fixtures for the Phase 10 PostgreSQL persistence tests.

The persistence tests deliberately require a real PostgreSQL database (see
``APS_TEST_DATABASE_URL``) and the optional ``postgres`` dependencies
(SQLAlchemy/Alembic/psycopg). They are skipped when either is absent so
engine-only/CLI workflows and environments without PostgreSQL keep working.
SQLite is never silently substituted when PostgreSQL semantics matter.
"""

import os

import pytest


def _reset_schema(url: str) -> None:
    """Drop and recreate the public schema for a deterministic test run."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    pytest.importorskip(
        "sqlalchemy", reason="optional 'postgres' dependencies are not installed"
    )
    from sqlalchemy import create_engine

    from aps_persistence.config import resolve_test_database_url

    url = resolve_test_database_url() or os.environ.get("APS_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "APS_TEST_DATABASE_URL is not set; PostgreSQL persistence tests skipped"
        )
    engine = create_engine(url, future=True)
    try:
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL test database not reachable: {exc}")
    finally:
        engine.dispose()
    return url


@pytest.fixture()
def migrated_database(test_database_url: str) -> str:
    """A migrated, freshly reset test database (schema at Alembic head)."""
    pytest.importorskip("alembic")
    from aps_persistence import migrate

    _reset_schema(test_database_url)
    migrate.upgrade(test_database_url)
    return test_database_url
