"""HTTP request/response schemas (Phase 9 P2/P3).

``PlanningRequest`` is the JSON body accepted by ``POST /plans``; its
``dataset`` field carries the Phase 8 dataset document (the object form of
``aps_engine.io.dataset_io.dataset_to_json``). ``PlanningResponse`` mirrors
the Phase 8 ResultDocument semantics: ``result`` (solver status, objective
value, diagnostics) plus ``schedule`` (``null`` for an infeasible plan).

The schema layer only describes the JSON contract. Domain validation of the
dataset document and objective happens in the service boundary before any
planner execution, so an invalid payload never reaches the solver.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PlanningParams(BaseModel):
    """Optional solver settings, mirroring ``SolverParams`` ints."""

    time_limit_seconds: int = Field(default=30, description="CP-SAT time limit in seconds.")
    num_search_workers: int = Field(default=2, description="Number of CP-SAT search workers.")
    random_seed: int = Field(default=42, description="CP-SAT random seed.")


class PlanningRequest(BaseModel):
    """POST /plans request body."""

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


class PlanningResponse(BaseModel):
    """POST /plans response body (ResultDocument-compatible)."""

    result: Dict[str, Any] = Field(
        description="Solve result information: status, objective value, "
        "diagnostics and solver counters (JSON-safe form of the Phase 8 "
        "persisted result document)."
    )
    schedule: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The extracted schedule, or null for an infeasible plan.",
    )
