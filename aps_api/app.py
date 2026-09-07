"""FastAPI application factory (Phase 9 P1).

The application is importable without starting a server: importing this
module builds the ``app`` object, and ``create_app()`` returns a fresh
instance for tests or embedding. No solver logic lives in route handlers -
the routes only read engine/package metadata.

S9-P1 provides the two system endpoints:

* ``GET /health``   - liveness probe (always 200 when the app is up).
* ``GET /version``  - the package version, read from the single package
  version source (``pyproject.toml`` distribution metadata) rather than
  being duplicated here.
"""

from fastapi import FastAPI

from aps_api.version import get_package_version, get_service_name


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    application = FastAPI(
        title="APS Engine API",
        description=(
            "Thin HTTP boundary over the APS Engine production scheduler. "
            "See /docs for the interactive OpenAPI documentation."
        ),
        version=get_package_version(),
    )

    @application.get("/health", tags=["system"])
    def health() -> dict:
        """Liveness probe."""
        return {"status": "ok", "service": get_service_name()}

    @application.get("/version", tags=["system"])
    def version() -> dict:
        """The package version from the single package version source."""
        return {"name": get_service_name(), "version": get_package_version()}

    return application


app = create_app()
