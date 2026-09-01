"""Weighted tardiness objective builder.

Objective: minimize ``sum(order.priority * tardiness(order))`` where
``tardiness(order) = max(0, end(last_operation) - order.due_time)``.

This is the engine's single objective and the default registered in
``aps_engine.objectives`` (Phase 7 P1). Selection through
``SolverParams.objective`` lands in a later part.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aps_engine.solver.model import ModelBuilder


def weighted_tardiness(builder: "ModelBuilder") -> None:
    """Add the weighted-tardiness objective to ``builder.model``.

    Creates one tardiness variable per order, records it on
    ``builder.tardiness`` (as the original inline implementation did) and
    minimizes the priority-weighted sum.
    """
    m = builder.model
    terms = []
    for order_id, order in builder.ds.orders.items():
        last = builder.ds.routings[order_id].operations[-1]
        tard = m.NewIntVar(0, builder.horizon_end, f"tard_{order_id}")
        m.AddMaxEquality(tard, [0, builder.end_i[last] - order.due_time])
        builder.tardiness[order_id] = tard
        terms.append(order.priority * tard)
    m.Minimize(sum(terms))
