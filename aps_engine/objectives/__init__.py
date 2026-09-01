"""Pluggable objective builders.

Phase 7 P1 extracts the hardcoded weighted-tardiness objective from
``solver.ModelBuilder._objective`` into this package and resolves objective
names to builder callables through a minimal registry. Phase 7 P2 adds a
deterministic makespan objective. Weighted tardiness remains the default;
CLI selection lands in a later Phase 7 part.
"""

from __future__ import annotations

from typing import Callable, Dict

from aps_engine.objectives.makespan import makespan
from aps_engine.objectives.weighted_tardiness import weighted_tardiness

ObjectiveBuilder = Callable[["ModelBuilder"], None]

_REGISTRY: Dict[str, ObjectiveBuilder] = {
    "weighted_tardiness": weighted_tardiness,
    "makespan": makespan,
}


def get_objective(name: str) -> ObjectiveBuilder:
    """Return the objective builder registered under ``name``.

    Raises ``KeyError`` for unknown names.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown objective: {name!r}") from None


def registered_objectives() -> tuple:
    """Return the names of all registered objectives (sorted)."""
    return tuple(sorted(_REGISTRY))
