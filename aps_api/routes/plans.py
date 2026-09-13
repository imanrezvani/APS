"""Planning route handlers (Phase 9 P2/P3, extended in Phase 10 P5).

``POST /plans`` accepts a Phase 8 dataset JSON document and returns the
planning result. The handler is deliberately thin: it parses the request,
delegates to the application boundary (``aps_api.service.PlanningService``)
and returns the JSON-safe response typed by :class:`aps_api.schemas`.
No solver/model logic and no SQL live here.

When persistence is configured the same ``POST /plans`` also stores the
dataset and a ``PlanningRun``; ``GET /plans`` and ``GET /plans/{plan_id}``
(read-only history) are then exposed and otherwise not mounted.
"""

from typing import List, Optional

from fastapi import APIRouter, Query, Request

from aps_api.schemas import (
    PlanDetail,
    PlanSummary,
    PlanningRequest,
    PlanningResponse,
)
from aps_api.service import PlanningService

router = APIRouter(tags=["plans"])
history_router = APIRouter(tags=["plans"])


def _service(http_request: Request) -> PlanningService:
    service: Optional[PlanningService] = getattr(
        http_request.app.state, "service", None
    )
    if service is None:
        raise RuntimeError("planning service is not configured on the application")
    return service


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
    document = _service(http_request).create_plan(payload.model_dump())
    return PlanningResponse.model_validate(document)


@history_router.get(
    "/plans",
    response_model=List[PlanSummary],
    summary="List persisted planning runs",
    description="Read-only planning-run history, optionally filtered by dataset.",
)
def list_plans(
    http_request: Request,
    dataset_id: Optional[str] = Query(default=None),
) -> List[PlanSummary]:
    records = _service(http_request).list_plans(dataset_id=dataset_id)
    return [PlanSummary.model_validate(record) for record in records]


@history_router.get(
    "/plans/{plan_id}",
    response_model=PlanDetail,
    summary="Get a persisted planning run",
)
def get_plan(plan_id: str, http_request: Request) -> PlanDetail:
    return PlanDetail.model_validate(_service(http_request).get_plan(plan_id))
