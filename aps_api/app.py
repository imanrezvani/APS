"""FastAPI application factory (Phase 9 P1/P2).

The application is importable without starting a server: importing this
module builds the ``app`` object, and ``create_app()`` returns a fresh
instance for tests or embedding. The application boundary
(``aps_api.service.PlanningService``) is attached to ``app.state`` so route
handlers delegate planning to it without ever touching the engine directly.

Endpoints:

* ``GET /health``  - liveness probe (always 200 when the app is up).
* ``GET /version`` - the package version, read from the single package
  version source (``pyproject.toml`` distribution metadata) rather than
  being duplicated here.
* ``POST /plans``  - submit a Phase 8 dataset JSON document and receive the
  planning result through the existing ``aps_engine.api.plan`` facade.
"""

from typing import Optional

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from aps_api.errors import (
    PlanningError,
    http_error_handler,
    planning_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from aps_api.routes.plans import router as plans_router
from aps_api.service import PlanningService
from aps_api.version import get_package_version, get_service_name


def create_app(service: Optional[PlanningService] = None) -> FastAPI:
    """Build and return the FastAPI application.

    ``service`` is injectable (S9-P5): a future async phase or an embedding
    host can substitute a job-backed ``PlanningService`` without changing the
    routes. It defaults to the synchronous service.
    """
    application = FastAPI(
        title="APS Engine API",
        description=(
            "Thin HTTP boundary over the APS Engine production scheduler. "
            "See /docs for the interactive OpenAPI documentation."
        ),
        version=get_package_version(),
    )
    application.state.service = service if service is not None else PlanningService()

    application.add_exception_handler(PlanningError, planning_error_handler)
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
    return application


app = create_app()
