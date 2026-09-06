"""Phase 8 solve-result JSON persistence.

``result_to_json`` serializes a solve output and ``result_from_json``
rebuilds it losslessly. A solve output is the dict returned by
:func:`aps_engine.solver.solver.solve` - ``{"result": SolveResult,
"schedule": ..., "builder": ...}``. Only the *document* is persisted:
``result`` (status/objective/diagnostics metadata) and ``schedule`` (when
a feasible solution exists). The raw CP-SAT ``builder`` - and any other
key in the output dict - is intentionally ignored and never serialized.

Round-trip guarantees
---------------------
* ``result`` is rebuilt as a real :class:`SolveResult` (so its ``optimal``
  property and ``== cp_model.OPTIMAL`` semantics keep working): the
  numeric CP-SAT status code is stored as an integer and restored to its
  ``CpSolverStatus`` enum value when known.
* ``schedule`` is preserved exactly (operation/order rows, start/end,
  machine/employee ids, per-order completion/tardiness, objective_value).
* Infeasible solves carry an empty diagnostics list only in the optimal
  case and root-cause diagnostics entries otherwise; those plain dicts are
  stored verbatim.
* The document carries a top-level ``"format"`` tag
  (``aps-engine.result.v1``) so a future schema change is detected and
  migrated explicitly. No parallel result model is introduced.

File helpers write/read the JSON document to/from a path. Dataset
serialization is intentionally not duplicated here: a solve output has no
Dataset reference, and datasets are persisted separately via
``aps_engine.io.dataset_io``.
"""

from json import dumps, loads
from pathlib import Path
from typing import Any, Dict

from ortools.sat.python.cp_model_helper import CpSolverStatus

from aps_engine.solver.model import SolveResult

FORMAT = "aps-engine.result.v1"

# SolveResult fields persisted verbatim (all JSON-safe scalars).
_RESULT_FIELDS = (
    "status",
    "feasible",
    "objective_value",
    "best_bound",
    "num_conflicts",
    "num_branches",
    "wall_time",
    "diagnostics",
)


def result_to_json(output: Dict[str, Any]) -> str:
    """Serialize a solve output dict to a JSON string.

    ``output`` must carry ``result`` (a
    :class:`~aps_engine.solver.model.SolveResult`) and may carry
    ``schedule`` (the dict from ``solve``, or None). Extra keys such as the
    raw CP-SAT ``builder`` are ignored.
    """
    result = output["result"]
    if not isinstance(result, SolveResult):
        raise TypeError(
            f"result_to_json expects output['result'] to be a SolveResult, "
            f"got {type(result).__name__}"
        )

    document: Dict[str, Any] = {
        "format": FORMAT,
        "result": {
            field: getattr(result, field) for field in _RESULT_FIELDS
        },
        "schedule": output.get("schedule"),
    }
    document["result"]["status_code"] = int(result.status_code)
    return dumps(document)


def result_from_json(data: Any) -> Dict[str, Any]:
    """Rebuild a solve output from a JSON string or a parsed JSON document.

    Returns ``{"result": SolveResult, "schedule": ...}`` (``schedule`` is
    None for an infeasible solve). Raises ``ValueError`` when the document
    does not carry the expected ``format`` tag.
    """
    if isinstance(data, str):
        document = loads(data)
    elif isinstance(data, dict):
        document = data
    else:
        raise ValueError(
            "result_from_json expects a JSON string or a parsed JSON dict, "
            f"got {type(data).__name__}"
        )

    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(
            f"unsupported result document (expected format {FORMAT!r})"
        )

    raw_result = document.get("result")
    if not isinstance(raw_result, dict):
        raise ValueError("result document is missing a 'result' object")

    payload: Dict[str, Any] = {
        field: raw_result.get(field) for field in _RESULT_FIELDS
    }
    payload["status_code"] = _restore_status_code(raw_result.get("status_code"))
    return {
        "result": SolveResult(**payload),
        "schedule": document.get("schedule"),
    }


def save_result(output: Dict[str, Any], path: Any) -> None:
    """Serialize ``output`` and write the JSON document to ``path``.

    ``path`` is a path-like object or string. Parent directories are
    created when missing.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result_to_json(output), encoding="utf-8")


def load_result(path: Any) -> Dict[str, Any]:
    """Load a JSON result document from ``path``.

    Returns the same structure as :func:`result_from_json`:
    ``{"result": SolveResult, "schedule": ...}``.
    """
    return result_from_json(Path(path).read_text(encoding="utf-8"))


def _restore_status_code(value: Any) -> int:
    """Restore the persisted numeric CP-SAT status to its enum value.

    Returns the enum member when ``value`` names a known status and the
    bare integer otherwise, so unknown/future status codes still round-trip
    without loss and ``SolveResult.optimal`` keeps its semantics.
    """
    try:
        return CpSolverStatus(int(value))
    except (TypeError, ValueError):
        return int(value)
