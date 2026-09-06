"""Phase 8 service API facade.

A small, stable programmatic boundary over the APS engine. ``plan`` is the
single entry point for future applications: it accepts a
:class:`~aps_engine.models.domain.Dataset` or the P1 JSON dataset document
(JSON text or parsed dict), selects an existing registered objective, runs
the existing solve pipeline and returns a machine-consumable
``ResultDocument`` - the same in-memory representation the P2 result
persistence layer serializes/deserializes.

The facade never exposes solver internals: ``ModelBuilder``, ``CpModel``,
``CpSolver``, ``IntVar``, ``IntervalVar`` and the raw ``solve()`` ``builder``
output are all hidden behind the returned document.

It is intentionally thin. It adds no scheduling behavior, no objectives and
no transport: no HTTP/ASGI/WSGI, database, queue, authentication or
multi-tenancy. Solver, model, generator and validator semantics are
untouched.
"""

from dataclasses import replace
from typing import Any, Dict, Optional, TypedDict, Union

from aps_engine.io.dataset_io import dataset_from_json
from aps_engine.models import Dataset
from aps_engine.objectives import get_objective
from aps_engine.solver.model import SolverParams, SolveResult


class ResultDocument(TypedDict):
    """Machine-consumable solve output.

    ``result`` carries the solver status, objective value and diagnostics
    (which include root-cause entries when an infeasible solve produced
    them); ``schedule`` is the extracted schedule, or None for an
    infeasible solve. This is exactly the representation
    ``aps_engine.io.result_io`` serializes, so a document returned by
    ``plan`` can be persisted verbatim with ``save_result``.
    """
    result: SolveResult
    schedule: Optional[Dict[str, Any]]


def plan(dataset_or_doc: Union[Dataset, str, Dict[str, Any]],
         objective: str = "weighted_tardiness",
         params: Optional[SolverParams] = None) -> ResultDocument:
    """Build, solve and return the schedule for ``dataset_or_doc``.

    ``dataset_or_doc`` is a Dataset, or the P1 JSON dataset document as
    either a JSON string (as produced by ``dataset_to_json``) or an
    already-parsed dict. ``objective`` selects an existing registered
    objective and defaults to ``weighted_tardiness``; an unknown name
    raises ``KeyError`` exactly like the objective registry / CLI. ``params``
    supplies the remaining solver settings; its own ``objective`` field is
    overridden by the ``objective`` argument.

    Returns a :class:`ResultDocument` (never the CP-SAT builder or any
    solver internals).
    """
    get_objective(objective)
    dataset = _coerce_dataset(dataset_or_doc)
    effective = SolverParams(objective=objective)
    if params is not None:
        effective = replace(params, objective=objective)
    output = _solve(dataset, effective)
    return {"result": output["result"], "schedule": output["schedule"]}


def _coerce_dataset(dataset_or_doc: Union[Dataset, str, Dict[str, Any]]) -> Dataset:
    """Resolve a Dataset or P1 JSON dataset document into a Dataset."""
    if isinstance(dataset_or_doc, Dataset):
        return dataset_or_doc
    if isinstance(dataset_or_doc, (str, dict)):
        return dataset_from_json(dataset_or_doc)
    raise TypeError(
        "plan expects a Dataset or a P1 JSON dataset document (string or "
        f"dict), got {type(dataset_or_doc).__name__}"
    )


def _solve(dataset: Dataset, params: SolverParams) -> Dict[str, Any]:
    """Run the existing solve pipeline and drop the raw builder."""
    from aps_engine.solver.solver import solve

    return solve(dataset, params)
