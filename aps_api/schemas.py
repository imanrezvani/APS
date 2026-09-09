"""HTTP request/response schemas (Phase 9 P2/P3).

``PlanningRequest`` is the JSON body accepted by ``POST /plans``; its
``dataset`` field carries the Phase 8 dataset document (the object form of
``aps_engine.io.dataset_io.dataset_to_json``). ``PlanningResponse`` mirrors
the Phase 8 ResultDocument semantics through explicit sub-models for the
solve/result information, the schedule and the diagnostics entries.

The schema layer only describes the JSON contract. Domain validation of the
dataset document and the objective happens in the service boundary before
any planner execution, so an invalid payload never reaches the solver.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlanningParams(BaseModel):
    """Optional solver settings, mirroring ``SolverParams`` ints."""

    model_config = {"extra": "forbid"}

    time_limit_seconds: int = Field(
        default=30, ge=1, le=3600, description="CP-SAT time limit in seconds."
    )
    num_search_workers: int = Field(
        default=2, ge=1, le=32, description="Number of CP-SAT search workers."
    )
    random_seed: int = Field(
        default=42, ge=0, description="CP-SAT random seed."
    )


class PlanningRequest(BaseModel):
    """POST /plans request body."""

    model_config = {"extra": "forbid"}

    dataset: Dict[str, Any] = Field(
        description="Dataset document in the Phase 8 JSON dataset format "
        "(see aps_engine.io.dataset_io)."
    )
    objective: str = Field(
        default="weighted_tardiness",
        description="Objective name from the engine objective registry "
        "(weighted_tardiness | makespan).",
    )
    params: Optional[PlanningParams] = Field(
        default=None, description="Optional solver settings."
    )


# ------------------------------------------------------------------ response

class Diagnostic(BaseModel):
    """One layered feasibility diagnostic entry."""

    model_config = {"extra": "forbid"}

    code: str
    order_id: Optional[str] = None
    operation_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    reason: str


class ResultInfo(BaseModel):
    """JSON-safe solve/result information (Phase 8 persisted form)."""

    model_config = {"extra": "forbid"}

    status: str
    status_code: int
    feasible: bool
    objective_value: Optional[float] = None
    best_bound: Optional[float] = None
    num_conflicts: int
    num_branches: int
    wall_time: float
    diagnostics: List[Diagnostic] = Field(default_factory=list)


class ScheduleOperation(BaseModel):
    """One scheduled operation row."""

    model_config = {"extra": "forbid"}

    operation_id: str
    order_id: str
    machine_id: Optional[str] = None
    employee_id: Optional[str] = None
    start: int
    end: int


class ScheduleOrder(BaseModel):
    """One scheduled order summary row."""

    model_config = {"extra": "forbid"}

    order_id: str
    completion_time: int
    due_time: int
    tardiness: int


class Schedule(BaseModel):
    """The extracted schedule document."""

    model_config = {"extra": "forbid"}

    operations: List[ScheduleOperation] = Field(default_factory=list)
    orders: List[ScheduleOrder] = Field(default_factory=list)
    objective_value: Optional[float] = None


class PlanningResponse(BaseModel):
    """POST /plans response body (ResultDocument-compatible)."""

    model_config = {"extra": "forbid"}

    result: ResultInfo
    schedule: Optional[Schedule] = None


class ErrorBody(BaseModel):
    """A single machine-readable error object."""

    model_config = {"extra": "forbid"}

    code: str
    message: str
    details: Optional[List[Any]] = None


class ErrorResponse(BaseModel):
    """Structured error envelope returned for every non-2xx response."""

    model_config = {"extra": "forbid"}

    error: ErrorBody
