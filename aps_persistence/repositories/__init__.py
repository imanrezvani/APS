"""Persistence repositories (Phase 10).

Each repository receives an explicit SQLAlchemy ``Session`` and owns all SQL
for its aggregate; application services own orchestration and transaction
boundaries. See :mod:`aps_persistence.repositories.dataset`.
"""

from aps_persistence.repositories.dataset import (
    DatasetNotFoundError,
    DatasetRepository,
)

__all__ = ["DatasetNotFoundError", "DatasetRepository"]
