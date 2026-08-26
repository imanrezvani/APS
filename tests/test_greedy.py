"""Deterministic greedy reference scheduler tests.

TEST 1: repeated execution produces identical results (determinism).
TEST 2: the material-feasible dataset yields a complete, validator-clean
        schedule with 0 violations.
TEST 3: the default (material-short) dataset never yields a falsely valid
        complete schedule.
TEST 4: precedence is respected inside every order chain.
TEST 5: operations never overlap on a shared machine and respect setup gaps.
TEST 6: operations never overlap on a shared employee.
TEST 7: machine compatibility and maintenance / downtime avoidance.
TEST 8: release times and the factory calendar are respected.
TEST 9: employee assignment (skill, work center, shift, availability).
TEST 10: the schedule covers every operation exactly once.
TEST 11: the reported objective matches the recomputed weighted tardiness.
TEST 12: the Dataset is never mutated.
"""

import copy

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.solver.greedy import greedy_solve
from aps_engine.validation.validator import validate


def _overlap(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e


def _working_slots(ds):
    """Ordered list of (start_abs, end_abs, shift_id) working shift slots."""
    slots = []
    for day in sorted(ds.calendar, key=lambda d: d.day_index):
        if not day.is_working:
            continue
        day_start = day.day_index * 1440
        for sid in day.shift_ids:
            sh = ds.shifts[sid]
            slots.append((day_start + sh.start_minute, day_start + sh.end_minute, sid))
    slots.sort()
    return slots


@pytest.fixture(scope="module")
def ds_feasible():
    return generate_dataset(material_feasible=True)


@pytest.fixture(scope="module")
def solved(ds_feasible):
    return greedy_solve(ds_feasible)


def _by_id(schedule):
    return {o["operation_id"]: o for o in schedule["operations"]}


# TEST 1 ----------------------------------------------------------------------
def test_deterministic_repeated_execution(ds_feasible):
    first = greedy_solve(ds_feasible)
    second = greedy_solve(ds_feasible)
    assert first["schedule"] == second["schedule"]
    assert first["result"].feasible == second["result"].feasible
    assert first["result"].status == second["result"].status
    assert first["result"].objective_value == second["result"].objective_value


# TEST 2 ----------------------------------------------------------------------
def test_feasible_dataset_complete_and_valid(ds_feasible, solved):
    result = solved["result"]
    assert result.feasible is True
    assert result.status == "FEASIBLE"
    assert solved["schedule"] is not None
    validation = validate(ds_feasible, solved["schedule"])
    assert validation.valid is True
    assert validation.violations == []


# TEST 3 ----------------------------------------------------------------------
def test_default_dataset_not_falsely_valid():
    ds = generate_dataset(material_feasible=False)
    out = greedy_solve(ds)
    assert out["result"].feasible is False
    assert out["result"].status == "INFEASIBLE"
    assert out["schedule"] is None
    assert out["result"].diagnostics
    assert any("M_HINGE" in d["message"] for d in out["result"].diagnostics)


# TEST 4 ----------------------------------------------------------------------
def test_precedence_respected(ds_feasible, solved):
    by_id = _by_id(solved["schedule"])
    for routing in ds_feasible.routings.values():
        for k in range(1, len(routing.operations)):
            prev, cur = routing.operations[k - 1], routing.operations[k]
            assert by_id[cur]["start"] >= by_id[prev]["end"]


# TEST 5 ----------------------------------------------------------------------
def test_machine_overlap_and_setup(ds_feasible, solved):
    by_machine = {}
    for o in solved["schedule"]["operations"]:
        by_machine.setdefault(o["machine_id"], []).append(o)
    for mid, ops in by_machine.items():
        ops.sort(key=lambda o: (o["start"], o["end"]))
        for a in range(len(ops)):
            for b in range(a + 1, len(ops)):
                assert not _overlap(ops[a]["start"], ops[a]["end"],
                                    ops[b]["start"], ops[b]["end"])
        for a in range(len(ops) - 1):
            nxt = ds_feasible.operations[ops[a + 1]["operation_id"]]
            assert ops[a + 1]["start"] >= ops[a]["end"] + nxt.setup_time


# TEST 6 ----------------------------------------------------------------------
def test_employee_overlap(ds_feasible, solved):
    by_employee = {}
    for o in solved["schedule"]["operations"]:
        if o["employee_id"] is not None:
            by_employee.setdefault(o["employee_id"], []).append(o)
    for eid, ops in by_employee.items():
        ops.sort(key=lambda o: (o["start"], o["end"]))
        for a in range(len(ops)):
            for b in range(a + 1, len(ops)):
                assert not _overlap(ops[a]["start"], ops[a]["end"],
                                    ops[b]["start"], ops[b]["end"])


# TEST 7 ----------------------------------------------------------------------
def test_machine_compatibility_and_windows(ds_feasible, solved):
    windows = list(ds_feasible.maintenance) + list(ds_feasible.downtime)
    for o in solved["schedule"]["operations"]:
        op = ds_feasible.operations[o["operation_id"]]
        assert o["machine_id"] in op.allowed_machine_ids
        for w in windows:
            if w.machine_id == o["machine_id"]:
                assert not _overlap(o["start"], o["end"], w.start, w.end)


# TEST 8 ----------------------------------------------------------------------
def test_release_and_calendar(ds_feasible, solved):
    slots = _working_slots(ds_feasible)
    for o in solved["schedule"]["operations"]:
        op = ds_feasible.operations[o["operation_id"]]
        order = ds_feasible.orders[op.order_id]
        assert o["start"] >= order.release_time
        assert any(s0 <= o["start"] and o["end"] <= s1 for s0, s1, _ in slots)


# TEST 9 ----------------------------------------------------------------------
def test_employee_assignment(ds_feasible, solved):
    for o in solved["schedule"]["operations"]:
        op = ds_feasible.operations[o["operation_id"]]
        if not op.employee_required:
            assert o["employee_id"] is None
            continue
        emp = ds_feasible.employees[o["employee_id"]]
        assert op.required_skill_id in emp.skill_ids
        assert op.work_center_id in emp.work_center_ids
        assert emp.available_from <= o["start"] and o["end"] <= emp.available_until


# TEST 10 ---------------------------------------------------------------------
def test_schedule_covers_every_operation(ds_feasible, solved):
    by_id = _by_id(solved["schedule"])
    assert set(by_id) == set(ds_feasible.operations)
    assert len(solved["schedule"]["operations"]) == len(ds_feasible.operations)
    assert len({o["operation_id"] for o in solved["schedule"]["operations"]}) \
        == len(ds_feasible.operations)


# TEST 11 ---------------------------------------------------------------------
def test_objective_matches_recomputed(ds_feasible, solved):
    by_id = _by_id(solved["schedule"])
    expected = 0.0
    for order_id, order in ds_feasible.orders.items():
        last = ds_feasible.routings[order_id].operations[-1]
        completion = by_id[last]["end"]
        tardiness = max(0, completion - order.due_time)
        expected += order.priority * tardiness
    assert solved["schedule"]["objective_value"] == float(expected)
    assert solved["result"].objective_value == float(expected)
    for rec in solved["schedule"]["orders"]:
        last = ds_feasible.routings[rec["order_id"]].operations[-1]
        assert rec["completion_time"] == by_id[last]["end"]
        assert rec["due_time"] == ds_feasible.orders[rec["order_id"]].due_time
        assert rec["tardiness"] == max(
            0, by_id[last]["end"] - ds_feasible.orders[rec["order_id"]].due_time)


# TEST 12 ---------------------------------------------------------------------
def test_dataset_not_mutated(ds_feasible):
    snapshot = copy.deepcopy(ds_feasible)
    greedy_solve(ds_feasible)
    assert ds_feasible == snapshot
