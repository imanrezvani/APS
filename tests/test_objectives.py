"""Phase 7 P1 objective extraction tests.

Covers the objectives registry, the extracted weighted-tardiness builder and
the guarantee that the default objective reproduces the pre-extraction
baseline (material-feasible dataset solves to OPTIMAL 39.0).
"""

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.objectives import get_objective, registered_objectives
from aps_engine.objectives.weighted_tardiness import weighted_tardiness
from aps_engine.solver.model import ModelBuilder, SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


def _reference_weighted_tardiness(builder):
    """Literal copy of the original inline ModelBuilder._objective() body."""
    m = builder.model
    terms = []
    for order_id, order in builder.ds.orders.items():
        last = builder.ds.routings[order_id].operations[-1]
        tard = m.NewIntVar(0, builder.horizon_end, f"tard_{order_id}")
        m.AddMaxEquality(tard, [0, builder.end_i[last] - order.due_time])
        builder.tardiness[order_id] = tard
        terms.append(order.priority * tard)
    m.Minimize(sum(terms))


@pytest.fixture(scope="module")
def material_feasible():
    return generate_dataset(material_feasible=True)


def test_registry_resolves_weighted_tardiness():
    assert get_objective("weighted_tardiness") is weighted_tardiness


def test_registry_unknown_objective_raises():
    with pytest.raises(KeyError):
        get_objective("not_an_objective")


def test_registered_objectives():
    assert registered_objectives() == ("makespan", "weighted_tardiness")


def test_default_objective_is_weighted_tardiness():
    assert SolverParams().objective == "weighted_tardiness"


def _objective_signature(model):
    """Canonical (variable name, coefficient) terms of a CpModel objective."""
    proto = model.Proto()
    names = [v.name for v in proto.variables]
    obj = proto.objective
    return sorted((names[vi], coeff) for vi, coeff in zip(obj.vars, obj.coeffs))


def test_extracted_objective_matches_reference_expression(material_feasible):
    """The extracted builder produces the identical CP-SAT objective."""
    built = ModelBuilder(material_feasible)
    built._declare_vars()
    weighted_tardiness(built)

    reference = ModelBuilder(material_feasible)
    reference._declare_vars()
    _reference_weighted_tardiness(reference)

    assert _objective_signature(built.model) == _objective_signature(reference.model)
    assert set(built.tardiness) == set(material_feasible.orders)


@pytest.fixture(scope="module")
def solved(material_feasible):
    out = solve(material_feasible, SolverParams(
        time_limit_seconds=30, num_search_workers=2, random_seed=42))
    return material_feasible, out


def test_default_solve_preserves_objective_39(solved):
    ds, out = solved
    assert out["result"].feasible, out["result"].status
    assert out["result"].objective_value == 39.0


def test_default_solve_schedule_is_valid(solved):
    ds, out = solved
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
