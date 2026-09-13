"""FastAPI application factory (Phase 9 P1/P2, extended in Phase 10 P5).

The application is importable without starting a server: importing this
module builds the ``app`` object, and ``create_app()`` returns a fresh
instance for tests or embedding. The application boundary
(``aps_api.service.PlanningService`` / ``DatasetService``) is attached to
``app.state`` so route handlers delegate planning/dataset work to it without
ever touching the engine or SQL directly.

Endpoints:

* ``GET /health``  - liveness probe (always 200 when the app is up).
* ``GET /version`` - the package version, read from the single package
  version source (``pyproject.toml`` distribution metadata).
* ``POST /plans``  - submit a Phase 8 dataset JSON document and receive the
  planning result through the existing ``aps_engine.api.plan`` facade.

When persistence is configured (``database=`` argument, or ``DATABASE_URL`` /
``APS_DATABASE_URL`` in the environment) the following are also mounted:

* ``POST /datasets``, ``GET /datasets``, ``GET /datasets/{dataset_id}``
* ``GET /plans``, ``GET /plans/{plan_id}``

Without a database the API is exactly the Phase 9 engine-only API; the
optional PostgreSQL dependencies are imported lazily.
"""

from typing import Optional

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from aps_api.errors import (
    NotFoundError,
    PlanningError,
    http_error_handler,
    not_found_error_handler,
    planning_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from aps_api.routes.datasets import router as datasets_router
from aps_api.routes.plans import history_router as plans_history_router
from aps_api.routes.plans import router as plans_router
from aps_api.service import DatasetService, PlanningService
from aps_api.version import get_package_version, get_service_name


def _persistence_from_env():
    """Build a ``Database`` from environment configuration, or return None.

    Kept lazy so importing the API never requires the optional ``postgres``
    dependencies or a configured database.
    """
    from aps_persistence.config import DatabaseConfigurationError, resolve_database_url

    try:
        url = resolve_database_url()
    except DatabaseConfigurationError:
        return None
    from aps_persistence.database import Database

    return Database.from_url(url)


def create_app(
    service: Optional[PlanningService] = None,
    *,
    database=None,
    dataset_service: Optional[DatasetService] = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    ``service``/``dataset_service`` are injectable so tests, an embedding
    host or a future async phase can substitute implementations without
    changing the routes. ``database`` enables the persistence endpoints; when
    omitted and no service is injected, the environment is consulted.
    """
    if service is None:
        if database is None:
            database = _persistence_from_env()
        service = PlanningService(database=database)
    if dataset_service is None and service.has_persistence:
        dataset_service = DatasetService(service.database)

    application = FastAPI(
        title="APS Engine API",
        description=(
            "Thin HTTP boundary over the APS Engine production scheduler. "
            "See /docs for the interactive OpenAPI documentation."
        ),
        version=get_package_version(),
    )
    application.state.service = service
    application.state.dataset_service = dataset_service

    application.add_exception_handler(PlanningError, planning_error_handler)
    application.add_exception_handler(NotFoundError, not_found_error_handler)
    application.add_exception_handler(
        RequestValidationError, validation_error_handler)
    application.add_exception_handler(
        StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    @application.get("/health", tags=["system"])
    def health() -> dict:
        """Liveness probe."""
        return {"status": "ok", "service": get_service_name()}

    @application.get("/version", tags=["system"])
    def version() -> dict:
        """The package version from the single package version source."""
        return {"name": get_service_name(), "version": get_package_version()}

    application.include_router(plans_router)
    if service.has_persistence:
        application.include_router(plans_history_router)
    if dataset_service is not None:
        application.include_router(datasets_router)
    return application


app = create_app()
