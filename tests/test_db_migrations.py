"""Phase 10 P1 migration-system tests (PostgreSQL + Alembic)."""

import pytest

pytest.importorskip("sqlalchemy", reason="optional 'postgres' dependencies not installed")
pytest.importorskip("alembic", reason="optional 'postgres' dependencies not installed")

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from aps_persistence import migrate  # noqa: E402

BASELINE = "0001_phase10_baseline"


def _head_revision(url: str) -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(migrate.alembic_config(url)).get_current_head()


def test_alembic_config_points_at_repo_migrations(test_database_url):
    config = migrate.alembic_config(test_database_url)
    assert config.get_main_option("script_location").endswith("alembic")


def test_upgrade_reaches_head_revision(migrated_database):
    engine = create_engine(migrated_database, future=True)
    try:
        assert "alembic_version" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == _head_revision(migrated_database)
    finally:
        engine.dispose()


def test_downgrade_and_reupgrade_is_deterministic(migrated_database):
    head = _head_revision(migrated_database)
    migrate.downgrade(migrated_database, "base")
    engine = create_engine(migrated_database, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
        assert rows == []
    finally:
        engine.dispose()

    migrate.upgrade(migrated_database)
    engine = create_engine(migrated_database, future=True)
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == head
    finally:
        engine.dispose()
