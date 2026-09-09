"""Planning service boundary (Phase 9 P2/P3/P5).

The route layer never touches the engine. ``PlanningService`` is the single
application-boundary entry point for planning and is deliberately thin: it
delegates execution to a :class:`aps_api.executor.PlanExecutor` (by default
the synchronous :class:`aps_api.executor.SyncPlanExecutor`). Executors
validate the request payload *before* any planner execution, invoke the
Phase 8 service facade (``aps_engine.api.plan``), and translate the engine
result into a JSON-safe response document using the Phase 8 persistence
representation (``aps_engine.io.result_io``) so solver enums and internal
objects never cross the HTTP boundary.

S9-P5 generalizes this module so a future phase can replace the synchronous
executor behind the same boundary (job creation + worker + result
retrieval) without rewriting the routes or the APS Engine.
"""

from typing import Any, Dict, Optional

from aps_api.executor import PlanExecutor, SyncPlanExecutor


class PlanningService:
    """Synchronous planning boundary over a :class:`PlanExecutor`.

    ``executor`` is injectable so tests and a future async phase can
    substitute a job-backed implementation without touching the routes.
    """

    def __init__(self, executor: Optional[PlanExecutor] = None) -> None:
        self._executor = executor if executor is not None else SyncPlanExecutor()

    @property
    def executor(self) -> PlanExecutor:
        return self._executor

    def create_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and run a planning request; return the JSON-safe payload.

        ``request`` mirrors :class:`aps_api.schemas.PlanningRequest`:
        ``dataset`` (dataset document), ``objective`` and optional ``params``.
        The returned dict is the ResultDocument-compatible
        ``{result, schedule}`` payload.
        """
        return self._executor.execute(request)
