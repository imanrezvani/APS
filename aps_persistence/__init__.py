"""APS Engine PostgreSQL persistence layer (Phase 10).

This package is a persistence/application infrastructure layer that sits
*above* the APS Engine: it stores Datasets and PlanningRuns in PostgreSQL
using SQLAlchemy, while the engine itself (``aps_engine``) stays completely
database-independent and never imports anything from here. The dependency
direction is one-way: ``aps_persistence`` -> ``aps_engine``.

Layering (Phase 10 target):

    FastAPI (aps_api)
        -> Application services
            -> Persistence (this package: repositories + session boundary)
                -> Dataset / PlanningRun (PostgreSQL)
                    -> aps_engine.api.plan()
                        -> APS Engine

Design notes
------------
* Configuration comes exclusively from environment variables (see
  :mod:`aps_persistence.config`); no credentials are hard-coded and no
  ``.env`` file is required or committed.
* Sessions have an explicit lifecycle and transactions are explicit
  (:mod:`aps_persistence.database`). There is no global mutable session.
* Repositories receive an explicit ``Session`` and own all SQL; application
  services own orchestration.
* The session/repository boundary is deliberately scoped by a
  ``dataset_id`` foreign key so a future phase can add physical
  database-per-tenant isolation by swapping the session factory, without
  rewriting repositories or business logic. Phase 10 does *not* implement
  tenants, tenant routing or RLS.

Phase 10 provides no authentication/authorization, multi-tenancy,
DB-per-tenant provisioning, frontend, async workers, billing, ERP/MES,
AI/Copilot or cloud deployment.
"""

from aps_persistence.config import (
    DatabaseConfigurationError,
    DatabaseSettings,
    settings_from_env,
)

__all__ = [
    "DatabaseConfigurationError",
    "DatabaseSettings",
    "settings_from_env",
]
