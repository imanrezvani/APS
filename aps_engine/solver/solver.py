"""Thin solve orchestration for Phase 1."""

from __future__ import annotations

from typing import Dict, Optional

from aps_engine.models import Dataset
from aps_engine.solver.model import ModelBuilder, SolverParams, SolveResult, extract_schedule


def solve(dataset: Dataset, params: Optional[SolverParams] = None) -> Dict:
    """Build, solve and extract the schedule. Returns {result, schedule}."""
    p = params or SolverParams()
    builder = ModelBuilder(dataset, p).build()
    result: SolveResult = builder.solve()
    schedule = extract_schedule(dataset, result, builder) if result.feasible else None
    return {"result": result, "schedule": schedule, "builder": builder}
