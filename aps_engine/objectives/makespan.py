"""Makespan objective builder.

Objective: minimize the end time of the last scheduled operation,
``makespan = max(end_time of all operations)``. Uses the existing per-operation
end variables (``builder.end_i``) so no additional constraint logic is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aps_engine.solver.model import ModelBuilder


def makespan(builder: "ModelBuilder") -> None:
    """Add the makespan objective to ``builder.model``.

    Creates a ``makespan`` variable equal to the maximum end time over all
    operations, records it on ``builder.makespan_var`` and minimizes it.
    """
    m = builder.model
    var = m.NewIntVar(0, builder.horizon_end, "makespan")
    m.AddMaxEquality(var, list(builder.end_i.values()))
    builder.makespan_var = var
    m.Minimize(var)
