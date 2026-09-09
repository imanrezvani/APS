"""Planning service boundary (Phase 9 P2/P3/P5).

The route layer never touches the engine. ``PlanningService`` is the single
application-boundary entry point for planning: it validates the request
payload *before* any planner execution, invokes the Phase 8 service facade
(``aps_engine.api.plan``), and translates the engine result into a JSON-safe
response document using the Phase 8 persistence representation
(``aps_engine.io.result_io``) so solver enums and internal objects never
cross the HTTP boundary.

S9-P5 generalizes this module so a future phase can replace the synchronous
executor behind the same boundary (job creation + worker + result retrieval)
without rewriting the routes or the APS Engine.
"""

import json
from typing import Any, Dict, Optional

from aps_engine.api import plan
from aps_engine.io.dataset_io import dataset_from_json
from aps_engine.io.result_io import result_to_json
from aps_engine.models import Dataset
from aps_engine.objectives import get_objective, registered_objectives
from aps_engine.solver.model import SolverParams

from aps_api.errors import PlanningError

_DEFAULT_PARAMS = dict(time_limit_seconds=30, num_search_workers=2, random_seed=42)


class PlanningService:
    """Synchronous planning boundary over ``aps_engine.api.plan``."""

    def create_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and run a planning request; return the JSON-safe payload.

        ``request`` mirrors :class:`aps_api.schemas.PlanningRequest`:
        ``dataset`` (dataset document), ``objective`` and optional ``params``.
        Validation happens before planner execution: an unparseable dataset
        document raises ``PlanningError`` (INVALID_DATASET_DOCUMENT) and an
        unknown objective raises ``PlanningError`` (UNKNOWN_OBJECTIVE) with
        the registry-consistent message. The returned dict is the
        ResultDocument-compatible ``{result, schedule}`` payload.
        """
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
