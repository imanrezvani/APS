"""Phase 10 P1 session-lifecycle and transaction tests (PostgreSQL)."""

import pytest

pytest.importorskip("sqlalchemy", reason="optional 'postgres' dependencies not installed")

from sqlalchemy import create_engine, text  # noqa: E402

from aps_persistence.database import Database, session_scope  # noqa: E402

_PROBE = "phase10_session_probe"


@pytest.fixture()
def probe_table(test_database_url):
    engine = create_engine(test_database_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {_PROBE}"))
        connection.execute(text(f"CREATE TABLE {_PROBE}(id integer PRIMARY KEY)"))
    yield test_database_url
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {_PROBE}"))
    engine.dispose()


def test_commit_persists_and_rollback_discards(probe_table):
    database = Database.from_url(probe_table)
    try:
        with database.session() as session:
            session.execute(text(f"INSERT INTO {_PROBE}(id) VALUES (1)"))

        with pytest.raises(RuntimeError):
            with database.session() as session:
                session.execute(text(f"INSERT INTO {_PROBE}(id) VALUES (2)"))
                raise RuntimeError("boom")

        with database.session() as session:
            ids = [row[0] for row in session.execute(text(f"SELECT id FROM {_PROBE} ORDER BY id"))]
        assert ids == [1]
    finally:
        database.dispose()


def test_session_scope_is_the_explicit_boundary(probe_table):
    database = Database.from_url(probe_table)
    try:
        with session_scope(database.session_factory) as session:
            session.execute(text(f"INSERT INTO {_PROBE}(id) VALUES (10)"))
        with session_scope(database.session_factory) as session:
            count = session.execute(text(f"SELECT count(*) FROM {_PROBE}")).scalar()
        assert count == 1
    finally:
        database.dispose()


def test_database_holds_no_open_session(test_database_url):
    database = Database.from_url(test_database_url)
    try:
        # The Database owns an engine and a session factory, never a session.
        assert database.engine is not None
        assert database.session_factory is not None
        # each unit of work gets its own Session object, never a shared one
        with database.session() as first:
            with database.session() as second:
                assert first is not second
        # two Database instances do not share mutable session state
        other = Database.from_url(test_database_url)
        try:
            assert database.session_factory is not other.session_factory
        finally:
            other.dispose()
    finally:
        database.dispose()
