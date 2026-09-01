"""Phase 7 P2 makespan objective tests.

Verifies the registry entry, that the objective is attached to the CP-SAT
model, and that solving the deterministic bundled material-feasible dataset
with makespan is OPTIMAL, deterministic and produces a schedule the
independent validator accepts. Weighted tardiness stays the default.
"""

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.objectives import get_objective
from aps_engine.objectives.makespan import makespan
from aps_engine.solver.model import ModelBuilder, SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


def test_registry_resolves_makespan():
    assert get_objective("makespan") is makespan


def test_default_objective_still_weighted_tardiness():
    assert SolverParams().objective == "weighted_tardiness"


def test_makespan_attached_to_model():
    ds = generate_dataset(material_feasible=True)
    builder = ModelBuilder(ds, SolverParams(objective="makespan"))
    builder._declare_vars()
    get_objective("makespan")(builder)

    assert builder.model.HasObjective()
    assert builder.makespan_var is not None
    proto = builder.model.Proto()
    names = [v.name for v in proto.variables]
    obj_var_names = [names[i] for i in proto.objective.vars]
    assert "makespan" in obj_var_names


@pytest.fixture(scope="module")
def solved_makespan():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, SolverParams(
        objective="makespan", time_limit_seconds=30,
        num_search_workers=2, random_seed=42))
    return ds, out


def test_makespan_solve_optimal_and_deterministic(solved_makespan):
    ds, out = solved_makespan
    assert out["result"].feasible, out["result"].status
    assert out["result"].optimal, out["result"].status

    again = solve(ds, SolverParams(
        objective="makespan", time_limit_seconds=30,
        num_search_workers=2, random_seed=42))
    assert again["result"].feasible, again["result"].status
    assert again["result"].optimal, again["result"].status
    assert again["result"].objective_value == out["result"].objective_value


def test_makespan_schedule_passes_validator(solved_makespan):
    ds, out = solved_makespan
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
