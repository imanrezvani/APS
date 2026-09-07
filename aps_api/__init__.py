"""APS Engine HTTP/application API (Phase 9).

A thin FastAPI application layer around the existing APS Engine. The HTTP
layer only exposes the engine through stable JSON contracts; all planning
logic lives behind the Phase 8 service facade (``aps_engine.api.plan``) and
is never duplicated inside route handlers.

Phase 9 provides no authentication, database, multi-tenancy, frontend,
async job workers or production deployment. Those belong to future phases.
"""

from aps_api.app import app, create_app

__all__ = ["app", "create_app"]
