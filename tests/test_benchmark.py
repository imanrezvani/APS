"""Phase 6 P2 benchmark harness tests.

TEST 1: both solvers receive the exact same Dataset instance.
TEST 2: the material-feasible dataset yields complete, valid schedules from
        both solvers with the expected statuses.
TEST 3: the default (material-short) dataset yields infeasible results from
        both solvers with no falsely valid schedule.
TEST 4: the infeasible-by-design dataset yields infeasible results from both
        solvers.
TEST 5: the report is deterministic except for measured runtimes.
TEST 6: the harness never mutates the Dataset.
TEST 7: the report carries all required per-solver fields and the formatted
        rendering covers status, objective, runtime, ops and validity.
"""

import copy

import pytest

from aps_engine.benchmarks.comparison import compare, format_report
from aps_engine.generator import generate_dataset, generate_infeasible_dataset
import aps_engine.benchmarks.comparison as comparison_mod


@pytest.fixture(scope="module")
def ds_feasible():
    return generate_dataset(material_feasible=True)


# TEST 1 ----------------------------------------------------------------------
def test_both_solvers_receive_same_dataset(monkeypatch, ds_feasible):
    seen = {}
    real_solve, real_greedy = comparison_mod.solve, comparison_mod.greedy_solve

    def spy_solve(ds, params=None):
        seen["cp-sat"] = ds
        return real_solve(ds, params)

    def spy_greedy(ds):
        seen["greedy"] = ds
        return real_greedy(ds)

    monkeypatch.setattr(comparison_mod, "solve", spy_solve)
    monkeypatch.setattr(comparison_mod, "greedy_solve", spy_greedy)
    comparison_mod.compare(ds_feasible)
    assert seen["cp-sat"] is ds_feasible
    assert seen["greedy"] is ds_feasible


# TEST 2 ----------------------------------------------------------------------
def test_feasible_dataset_complete_and_valid(ds_feasible):
    report = compare(ds_feasible)
    cp, greedy = report["runs"]["cp-sat"], report["runs"]["greedy"]
    for row in (cp, greedy):
        assert row["feasible"] is True
        assert row["valid"] is True
        assert row["n_violations"] == 0
        assert row["violation_codes"] == []
        assert row["operations_scheduled"] == ds_feasible.meta["n_operations"]
        assert row["objective"] is not None
    assert cp["status"] == "OPTIMAL"
    assert greedy["status"] == "FEASIBLE"
    assert report["comparison"]["feasibility_agreement"] is True
    assert report["comparison"]["objective_delta"] == cp["objective"] - greedy["objective"]


# TEST 3 ----------------------------------------------------------------------
def test_default_dataset_infeasible():
    ds = generate_dataset(material_feasible=False)
    report = compare(ds)
    for row in report["runs"].values():
        assert row["feasible"] is False
        assert row["valid"] is False
        assert row["operations_scheduled"] == 0
        assert row["objective"] is None
        assert "NO_SCHEDULE" in row["violation_codes"]
    assert report["comparison"]["feasibility_agreement"] is True
    assert report["comparison"]["objective_delta"] is None


# TEST 4 ----------------------------------------------------------------------
def test_infeasible_by_design_dataset():
    ds = generate_infeasible_dataset()
    report = compare(ds)
    assert report["comparison"]["feasibility_agreement"] is True
    assert report["runs"]["cp-sat"]["feasible"] is False
    assert report["runs"]["greedy"]["feasible"] is False
    assert report["runs"]["cp-sat"]["valid"] is False
    assert report["runs"]["greedy"]["valid"] is False


# TEST 5 ----------------------------------------------------------------------
def test_report_deterministic_except_runtime(ds_feasible):
    first = compare(ds_feasible)
    second = compare(ds_feasible)
    for row in first["runs"].values():
        row["runtime_s"] = None
    first["comparison"]["runtime_speedup_greedy_vs_cpsat"] = None
    for row in second["runs"].values():
        row["runtime_s"] = None
    second["comparison"]["runtime_speedup_greedy_vs_cpsat"] = None
    assert first == second


# TEST 6 ----------------------------------------------------------------------
def test_compare_does_not_mutate_dataset(ds_feasible):
    snapshot = copy.deepcopy(ds_feasible)
    compare(ds_feasible)
    assert ds_feasible == snapshot


# TEST 7 ----------------------------------------------------------------------
def test_report_fields_and_format(ds_feasible):
    report = compare(ds_feasible)
    assert set(report["runs"]) == {"cp-sat", "greedy"}
    for row in report["runs"].values():
        assert set(row) == {"solver", "status", "feasible", "objective",
                            "runtime_s", "operations_scheduled", "valid",
                            "n_violations", "violation_codes"}
    text = format_report(report)
    assert "cp-sat" in text and "greedy" in text
    assert "status" in text and "objective" in text
    assert "runtime" in text and "ops" in text and "valid" in text
    assert "violations" in text and "feasibility_agreement" in text
