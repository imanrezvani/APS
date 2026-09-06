"""Phase 8 P2 solve-result JSON persistence tests.

Verifies lossless round-trips of the real solve outputs for both supported
objectives (weighted_tardiness OPTIMAL 39.0, makespan OPTIMAL 1350.0), of
schedules and of root-cause diagnostics on infeasible solves, the explicit
versioned JSON document format, the write -> load file cycle, deterministic
output, that the raw CP-SAT builder is never persisted, and that a loaded
schedule still passes the independent validator.
"""

import json

import pytest
from ortools.sat.python.cp_model_helper import CpSolverStatus

from aps_engine.generator import generate_dataset
from aps_engine.io.dataset_io import dataset_from_json, dataset_to_json
from aps_engine.io.result_io import (
    FORMAT,
    load_result,
    result_from_json,
    result_to_json,
    save_result,
)
from aps_engine.solver.model import SolveResult, SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate

_PARAMS = dict(time_limit_seconds=30, num_search_workers=2, random_seed=42)


@pytest.fixture(scope="module")
def material_dataset():
    return generate_dataset(material_feasible=True, sequence_dependent_setup=True)


@pytest.fixture(scope="module")
def solved_weighted(material_dataset):
    return solve(
        material_dataset,
        SolverParams(objective="weighted_tardiness", **_PARAMS))


@pytest.fixture(scope="module")
def solved_makespan(material_dataset):
    return solve(material_dataset, SolverParams(objective="makespan", **_PARAMS))


@pytest.fixture(scope="module")
def solved_infeasible():
    return solve(generate_dataset(material_feasible=False), SolverParams())


def test_optimal_result_roundtrip(solved_weighted):
    back = result_from_json(result_to_json(solved_weighted))
    original = solved_weighted["result"]
    loaded = back["result"]
    assert isinstance(loaded, SolveResult)
    assert loaded.status == original.status
    assert loaded.status_code == original.status_code
    assert loaded.feasible == original.feasible
    assert loaded.objective_value == original.objective_value
    assert loaded.best_bound == original.best_bound
    assert loaded.num_conflicts == original.num_conflicts
    assert loaded.num_branches == original.num_branches
    assert loaded.wall_time == original.wall_time
    assert loaded.optimal


def test_status_code_restored_as_enum(solved_weighted):
    back = result_from_json(result_to_json(solved_weighted))
    assert type(back["result"].status_code) is type(CpSolverStatus.OPTIMAL)
    assert back["result"].status_code == CpSolverStatus.OPTIMAL


def test_schedule_roundtrip(solved_weighted):
    back = result_from_json(result_to_json(solved_weighted))
    assert back["schedule"] == solved_weighted["schedule"]
    assert back["schedule"]["objective_value"] == 39.0


def test_optimal_diagnostics_empty_roundtrip(solved_weighted):
    back = result_from_json(result_to_json(solved_weighted))
    assert back["result"].diagnostics == []


def test_diagnostics_roundtrip(solved_infeasible):
    back = result_from_json(result_to_json(solved_infeasible))
    assert not solved_infeasible["result"].feasible
    assert back["schedule"] is None
    assert len(back["result"].diagnostics) == len(
        solved_infeasible["result"].diagnostics)
    assert back["result"].diagnostics == solved_infeasible["result"].diagnostics


def test_root_cause_information_roundtrip(solved_infeasible):
    back = result_from_json(result_to_json(solved_infeasible))
    codes = {d["code"] for d in back["result"].diagnostics}
    assert "MATERIAL_SHORTAGE" in codes
    for original, loaded in zip(
            solved_infeasible["result"].diagnostics,
            back["result"].diagnostics):
        assert original == loaded
        for key in ("code", "reason", "resource_type", "resource_id"):
            assert loaded[key] == original[key]


def test_json_validity_and_format_tag(solved_weighted):
    text = result_to_json(solved_weighted)
    document = json.loads(text)
    assert document["format"] == FORMAT
    assert set(document) == {"format", "result", "schedule"}
    assert set(document["result"]) == {
        "status", "status_code", "feasible", "objective_value", "best_bound",
        "num_conflicts", "num_branches", "wall_time", "diagnostics"}


def test_write_load_file_cycle(solved_weighted, tmp_path):
    results_dir = tmp_path / "data" / "results"
    path = results_dir / "weighted_tardiness.json"
    save_result(solved_weighted, path)
    assert path.exists()
    loaded = load_result(path)
    assert loaded["result"] == solved_weighted["result"]
    assert loaded["schedule"] == solved_weighted["schedule"]


def test_loaded_schedule_passes_validator(material_dataset, solved_weighted):
    loaded = result_from_json(result_to_json(solved_weighted))
    validation = validate(material_dataset, loaded["schedule"])
    assert validation.valid, [v.message for v in validation.violations]


@pytest.mark.parametrize("objective,expected", [
    ("weighted_tardiness", 39.0),
    ("makespan", 1350.0),
], ids=["weighted-tardiness", "makespan"])
def test_objective_parity_after_roundtrip(
        material_dataset, objective, expected, request):
    fixture = {"weighted_tardiness": "solved_weighted",
               "makespan": "solved_makespan"}[objective]
    solved = request.getfixturevalue(fixture)
    loaded = result_from_json(result_to_json(solved))
    assert loaded["result"].feasible
    assert loaded["result"].optimal
    assert loaded["result"].objective_value == expected
    assert loaded["result"].objective_value == solved["result"].objective_value
    assert validate(material_dataset, loaded["schedule"]).valid


def test_deterministic_roundtrip(solved_weighted):
    assert result_to_json(solved_weighted) == result_to_json(solved_weighted)
    loaded_a = result_from_json(result_to_json(solved_weighted))
    loaded_b = result_from_json(result_to_json(solved_weighted))
    assert loaded_a == loaded_b


def test_persisted_document_has_no_raw_builder_or_cp_object(solved_weighted):
    assert "builder" in solved_weighted
    text = result_to_json(solved_weighted)
    assert "builder" not in text
    assert "CpModel" not in text
    assert "IntVar" not in text
    json.loads(text)  # any residual CP-SAT object would make this raise


def test_format_mismatch_rejected():
    with pytest.raises(ValueError):
        result_from_json({"format": "aps-engine.result.v0"})


def test_result_is_reusable_with_p1_dataset_persistence(material_dataset):
    dataset_document = dataset_to_json(material_dataset)
    dataset_copy = dataset_from_json(dataset_document)
    assert dataset_copy == material_dataset
