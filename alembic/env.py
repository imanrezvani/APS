"""Alembic environment (Phase 10 P1).

Resolves the database URL from the shared environment configuration and
targets the persistence metadata. The APS Engine is never imported here;
only the SQLAlchemy persistence metadata is used as the autogenerate target.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from aps_persistence.base import Base
from aps_persistence.config import resolve_database_url

# Import the model modules so their tables register on Base.metadata.
# Guarded so the P1 foundation works before models exist.
try:  # pragma: no cover - trivial import guard
    import aps_persistence.models  # noqa: F401
except ImportError:  # pragma: no cover
    pass

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or resolve_database_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = create_engine(_database_url(), poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
