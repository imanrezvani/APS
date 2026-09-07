"""Planning route handlers (Phase 9 P2).

``POST /plans`` accepts a Phase 8 dataset JSON document and returns the
planning result. The handler is deliberately thin: it parses the request,
delegates to the application boundary (``aps_api.service.PlanningService``)
and returns the JSON-safe response. No solver/model logic lives here.
"""

from typing import Optional

from fastapi import APIRouter, Request

from aps_api.schemas import PlanningRequest, PlanningResponse
from aps_api.service import PlanningService

router = APIRouter(tags=["plans"])


@router.post(
    "/plans",
    response_model=PlanningResponse,
    summary="Create a production plan",
    description=(
        "Submit a dataset document in the Phase 8 JSON dataset format and "
        "receive the scheduling result. An infeasible dataset is a valid "
        "planning result (HTTP 200 with schedule=null and diagnostics), not "
        "an API failure."
    ),
)
def create_plan(payload: PlanningRequest, http_request: Request) -> PlanningResponse:
    service: Optional[PlanningService] = getattr(http_request.app.state, "service", None)
    if service is None:
        raise RuntimeError("planning service is not configured on the application")
    document = service.create_plan(payload.model_dump())
    return PlanningResponse(**document)
