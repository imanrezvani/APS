"""Engine / session factory and explicit session lifecycle (Phase 10 P1).

Design
------
* ``create_db_engine`` / ``create_session_factory`` are pure factories.
* ``Database`` bundles a settings object, one engine and one session factory.
  The session factory is *not* a global: it is owned by the ``Database``
  instance and passed explicitly to repositories/application services.
* ``session_scope`` gives every unit of work an explicit lifecycle:
  ``begin -> commit`` on success, ``rollback`` on error, always ``close``.
  There is no shared/global mutable ``Session`` anywhere.
* The engine is never created at import time, so engine-only/CLI workflows
  run without a database and without ``DATABASE_URL``.

Future physical DB-per-tenant isolation is reached by injecting a different
session factory (one per tenant database) into the same repositories; no
repository or business-logic change is required. Phase 10 does not implement
tenant routing.
"""

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aps_persistence.config import DatabaseSettings, settings_from_env


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine from resolved settings."""
    return create_engine(settings.url, **settings.engine_kwargs())


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create a session factory bound to ``engine``.

    ``expire_on_commit=False`` keeps persisted attribute values readable
    after commit, so callers can serialize a repository result without
    triggering lazy loads after the transaction closed.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker) -> Iterator[Session]:
    """Explicit unit-of-work context: commit on success, rollback on error.

    Always closes the session. Callers must not hold the session beyond the
    ``with`` block.
    """
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    """An engine + session factory pair with an explicit lifecycle.

    The instance is cheap to create and is safe to pass around, but it is
    *not* a global singleton and holds no open session: sessions are opened
    per unit of work through :meth:`session` / :func:`session_scope`.
    """

    def __init__(
        self,
        settings: Optional[DatabaseSettings] = None,
        *,
        url: Optional[str] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        if engine is not None and settings is not None:
            raise ValueError("pass either engine or settings, not both")
        self.settings = settings
        self.engine = engine if engine is not None else create_db_engine(
            settings if settings is not None else settings_from_env(url)
        )
        self.session_factory = create_session_factory(self.engine)

    @classmethod
    def from_url(cls, url: str, **kwargs) -> "Database":
        return cls(settings_from_env(url), **kwargs)

    def session(self) -> "contextmanager":
        """Return the explicit session-scope context manager."""
        return session_scope(self.session_factory)

    def dispose(self) -> None:
        """Dispose the connection pool (close all idle connections)."""
        self.engine.dispose()
