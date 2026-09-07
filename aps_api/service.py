"""Planning service boundary (Phase 9 P2/P5).

The route layer never touches the engine. ``PlanningService`` is the single
application-boundary entry point for planning: it validates the request
payload, invokes the Phase 8 service facade (``aps_engine.api.plan``), and
translates the engine result into a JSON-safe response document using the
Phase 8 persistence representation (``aps_engine.io.result_io``) so solver
enums and internal objects never cross the HTTP boundary.

S9-P5 generalizes this module so a future phase can replace the synchronous
executor behind the same boundary (job creation + worker + result retrieval)
without rewriting the routes or the APS Engine.
"""

import json
from typing import Any, Dict, Optional

from aps_engine.api import plan
from aps_engine.io.result_io import result_to_json
from aps_engine.solver.model import SolverParams

_DEFAULT_PARAMS = dict(time_limit_seconds=30, num_search_workers=2, random_seed=42)


class PlanningService:
    """Synchronous planning boundary over ``aps_engine.api.plan``."""

    def create_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run a planning request and return the JSON-safe response payload.

        ``request`` mirrors :class:`aps_api.schemas.PlanningRequest`:
        ``dataset`` (dataset document), ``objective`` and optional ``params``.
        The returned dict is the ResultDocument-compatible ``{result,
        schedule}`` payload (see :class:`aps_api.schemas.PlanningResponse`).
        """
        objective = request.get("objective", "weighted_tardiness")
        solver_params = _solver_params(objective, request.get("params"))

        document = plan(request["dataset"], objective=objective, params=solver_params)
        payload = json.loads(result_to_json(document))
        return {"result": payload["result"], "schedule": payload["schedule"]}


def _solver_params(objective: str, params: Optional[Dict[str, Any]]) -> SolverParams:
    """Build the SolverParams for a request, defaulting like the engine."""
    overrides = _DEFAULT_PARAMS.copy()
    if params:
        for key in _DEFAULT_PARAMS:
            if key in params and params[key] is not None:
                overrides[key] = params[key]
    return SolverParams(objective=objective, **overrides)
