"""Phase 8 P3 service API facade tests.

Verifies ``plan`` as the programmatic boundary: Dataset and P1 JSON
document inputs (string and parsed dict), both registered objectives, the
returned ResultDocument (result + schedule, never the raw builder/CP-SAT
objects), preserved diagnostics and root-cause information on infeasible
solves, registry/CLI-consistent unknown-objective errors, P2 persistence
compatibility, and that representative schedules pass the independent
validator.
"""

import json

import pytest

import aps_engine
from aps_engine.api import ResultDocument, plan
from aps_engine.generator import generate_dataset
from aps_engine.io.dataset_io import dataset_to_json
from aps_engine.io.result_io import (
    load_result,
    result_from_json,
    result_to_json,
    save_result,
)
from aps_engine.objectives import get_objective
from aps_engine.solver.model import SolveResult, SolverParams
from aps_engine.validation.validator import validate

_PARAMS = dict(time_limit_seconds=30, num_search_workers=2, random_seed=42)


@pytest.fixture(scope="module")
def material_dataset():
    return generate_dataset(material_feasible=True, sequence_dependent_setup=True)


@pytest.fixture(scope="module")
def material_document(material_dataset):
    return dataset_to_json(material_dataset)


@pytest.fixture(scope="module")
def solved_weighted(material_dataset):
    return plan(material_dataset, params=SolverParams(**_PARAMS))


@pytest.fixture(scope="module")
def solved_makespan(material_dataset):
    return plan(
        material_dataset, objective="makespan", params=SolverParams(**_PARAMS))


@pytest.fixture(scope="module")
def solved_infeasible():
    return plan(generate_dataset(material_feasible=False))


def test_facade_reexported():
    assert aps_engine.plan is plan
    assert aps_engine.ResultDocument is ResultDocument


def test_dataset_input_default_objective(material_dataset):
    document = plan(material_dataset)
    assert document["result"].objective_value == 39.0
    assert document["result"].optimal
    assert document["result"].status == "OPTIMAL"


def test_json_document_string_input(material_document):
    document = plan(material_document)
    assert document["result"].objective_value == 39.0
    assert document["schedule"] is not None


def test_json_document_parsed_dict_input(material_dataset):
    parsed = json.loads(dataset_to_json(material_dataset))
    document = plan(parsed)
    assert document["result"].objective_value == 39.0


def test_result_and_schedule_shape(solved_weighted):
    assert set(solved_weighted) == {"result", "schedule"}
    assert isinstance(solved_weighted["result"], SolveResult)
    assert set(solved_weighted["schedule"]) == {
        "operations", "orders", "objective_value"}
    assert solved_weighted["schedule"]["objective_value"] == 39.0
    assert all(op["operation_id"] for op in solved_weighted["schedule"]["operations"])
    assert all(ord_["order_id"] for ord_ in solved_weighted["schedule"]["orders"])


@pytest.mark.parametrize("objective,expected", [
    ("weighted_tardiness", 39.0),
    ("makespan", 1350.0),
], ids=["weighted-tardiness", "makespan"])
def test_objectives(material_dataset, objective, expected, request):
    fixture = {"weighted_tardiness": "solved_weighted",
               "makespan": "solved_makespan"}[objective]
    document = request.getfixturevalue(fixture)
    assert document["result"].feasible
    assert document["result"].optimal
    assert document["result"].objective_value == expected


def test_diagnostics_preserved(solved_infeasible):
    assert not solved_infeasible["result"].feasible
    assert solved_infeasible["schedule"] is None
    assert len(solved_infeasible["result"].diagnostics) > 0
    for entry in solved_infeasible["result"].diagnostics:
        assert set(entry) >= {"code", "reason", "resource_type", "resource_id"}


def test_root_cause_preserved_when_present(solved_infeasible):
    codes = {entry["code"] for entry in solved_infeasible["result"].diagnostics}
    assert "MATERIAL_SHORTAGE" in codes
    shortage = next(
        e for e in solved_infeasible["result"].diagnostics
        if e["code"] == "MATERIAL_SHORTAGE")
    assert shortage["resource_type"] == "material"
    assert shortage["resource_id"]


def test_no_raw_builder_or_cp_sat_exposed(solved_weighted):
    assert set(solved_weighted) == {"result", "schedule"}
    result = solved_weighted["result"]
    for name in ("builder", "model", "solver", "cp_model"):
        assert not hasattr(result, name)
    text = result_to_json(solved_weighted)
    for forbidden in ("builder", "CpModel", "CpSolver", "IntVar", "IntervalVar"):
        assert forbidden not in text


def test_invalid_objective_matches_registry(material_dataset):
    with pytest.raises(KeyError) as excinfo:
        plan(material_dataset, objective="bogus")
    assert "unknown objective" in str(excinfo.value)
    assert "bogus" in str(excinfo.value)
    assert get_objective("weighted_tardiness") is not None


def test_unknown_objective_does_not_solve(material_dataset):
    with pytest.raises(KeyError):
        plan(material_dataset, objective="bogus")


def test_p2_persistence_compatibility(solved_weighted, tmp_path):
    path = tmp_path / "plan.json"
    save_result(solved_weighted, path)
    loaded = load_result(path)
    assert loaded == result_from_json(result_to_json(solved_weighted))
    assert loaded["result"] == solved_weighted["result"]
    assert loaded["schedule"] == solved_weighted["schedule"]


def test_schedules_pass_validator(material_dataset, solved_weighted, solved_makespan):
    for document in (solved_weighted, solved_makespan):
        result = validate(material_dataset, document["schedule"])
        assert result.valid, [v.message for v in result.violations]


def test_params_objective_overridden(material_dataset):
    params = SolverParams(objective="makespan", **_PARAMS)
    document = plan(material_dataset, objective="weighted_tardiness", params=params)
    assert document["result"].objective_value == 39.0


def test_invalid_input_type_rejected():
    with pytest.raises(TypeError):
        plan(object())
