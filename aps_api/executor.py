"""Executors: the async-ready planning boundary (Phase 9 P5).

A single minimal abstraction separates *what* a planning request computes
from *how/when* it is executed. ``PlanExecutor.execute(request)`` is the
only contract the service boundary depends on; the engine is reached
exclusively through the Phase 8 facade ``aps_engine.api.plan`` and the
Phase 8 persistence representation.

A future phase can evolve

    POST /plans
      -> synchronous execution (today: SyncPlanExecutor)

into

    POST /plans            -> job creation (queue id)
      -> worker            -> runs PlanExecutor.execute(...)
      -> result retrieval  -> returns the same payload

without rewriting the routes, the service boundary, the payload contract or
the core APS Engine. The future job worker simply runs the exact same
executor behind a queue facade. No Celery/Redis/broker infrastructure is
implemented or imported here; this module is architectural preparation only.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from aps_engine.api import plan
from aps_engine.io.dataset_io import dataset_from_json
from aps_engine.io.result_io import result_to_json
from aps_engine.models import Dataset
from aps_engine.objectives import get_objective, registered_objectives
from aps_engine.solver.model import SolverParams

from aps_api.errors import PlanningError

_DEFAULT_PARAMS = dict(time_limit_seconds=30, num_search_workers=2, random_seed=42)


class PlanExecutor(ABC):
    """Computes a planning request payload for a backend execution model.

    Synchronous (``SyncPlanExecutor``) today; a future async backend swaps
    this for a job-backed executor behind the same interface.
    """

    @abstractmethod
    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ResultDocument-compatible ``{result, schedule}`` payload.

        Raises :class:`aps_api.errors.PlanningError` for invalid dataset
        documents or unknown objectives *before* any planner execution.
        """


class SyncPlanExecutor(PlanExecutor):
    """Deterministic in-process executor used by the synchronous API."""

    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        dataset_document = request["dataset"]
        objective = request.get("objective", "weighted_tardiness")
        solver_params = _solver_params(objective, request.get("params"))

        dataset = _validate_dataset(dataset_document)
        _validate_objective(objective)

        document = plan(dataset, objective=objective, params=solver_params)
        payload = json.loads(result_to_json(document))
        return {"result": payload["result"], "schedule": payload["schedule"]}


def _validate_dataset(dataset_document: Any) -> Dataset:
    """Parse/validate the Phase 8 dataset document before execution."""
    try:
        return dataset_from_json(dataset_document)
    except (TypeError, ValueError) as exc:
        raise PlanningError(
            "INVALID_DATASET_DOCUMENT",
            f"dataset is not a valid Phase 8 dataset document: {exc}",
        ) from exc


def _validate_objective(objective: str) -> None:
    """Validate the objective against the engine registry before execution."""
    try:
        get_objective(objective)
    except KeyError:
        valid = ", ".join(registered_objectives())
        raise PlanningError(
            "UNKNOWN_OBJECTIVE",
            f"unknown objective {objective!r} (valid: {valid})",
        ) from None


def _solver_params(objective: str, params: Optional[Dict[str, Any]]) -> SolverParams:
    """Build the SolverParams for a request, defaulting like the engine."""
    overrides = _DEFAULT_PARAMS.copy()
    if params:
        for key in _DEFAULT_PARAMS:
            if key in params and params[key] is not None:
                overrides[key] = params[key]
    return SolverParams(objective=objective, **overrides)
