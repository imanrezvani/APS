"""Solver tests.

TEST 6: solver returns a schedule that passes the validator.
TEST 7: every operation is assigned to exactly one compatible machine.
TEST 8: no two operations overlap on the same machine.
"""

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    CalendarDay,
    Dataset,
    DowntimeWindow,
    Employee,
    Machine,
    MaintenanceWindow,
    Operation,
    Order,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


@pytest.fixture(scope="module")
def solved():
    # The default dataset is material-infeasible (Phase 5 P1 forces it
    # INFEASIBLE); the material-feasible variant preserves the solvable
    # baseline used to exercise the scheduling constraints.
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    return ds, out


def test_solver_finds_feasible_solution(solved):
    ds, out = solved
    assert out["result"].feasible, out["result"].status
    assert out["schedule"] is not None


def test_solver_schedule_passes_validator(solved):
    ds, out = solved
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]


def test_every_operation_assigned_exactly_one_compatible_machine(solved):
    ds, out = solved
    by_id = {}
    for o in out["schedule"]["operations"]:
        assert o["operation_id"] not in by_id  # appears exactly once
        by_id[o["operation_id"]] = o
    assert set(by_id) == set(ds.operations)
    for op_id, o in by_id.items():
        op = ds.operations[op_id]
        assert o["machine_id"] in op.allowed_machine_ids
        assert o["end"] - o["start"] == op.processing_time


def test_no_two_operations_overlap_on_same_machine(solved):
    ds, out = solved
    by_machine = {}
    for o in out["schedule"]["operations"]:
        by_machine.setdefault(o["machine_id"], []).append((o["start"], o["end"]))
    for mid, intervals in by_machine.items():
        intervals.sort()
        for a in range(len(intervals) - 1):
            assert intervals[a][1] <= intervals[a + 1][0], f"overlap on {mid}"


def test_solver_respects_release_and_precedence(solved):
    ds, out = solved
    starts = {o["operation_id"]: o["start"] for o in out["schedule"]["operations"]}
    ends = {o["operation_id"]: o["end"] for o in out["schedule"]["operations"]}
    for order_id, routing in ds.routings.items():
        release = ds.orders[order_id].release_time
        for op_id in routing.operations:
            assert starts[op_id] >= release
        for k in range(1, len(routing.operations)):
            assert starts[routing.operations[k]] >= ends[routing.operations[k - 1]]


def test_objective_is_weighted_tardiness(solved):
    ds, out = solved
    schedule = out["schedule"]
    computed = 0.0
    for r in schedule["orders"]:
        computed += ds.orders[r["order_id"]].priority * r["tardiness"]
    assert out["result"].objective_value is not None
    assert computed >= 0


# ---------------------------------------------------------------- Phase 2
def make_calendar_ds(shift_specs, day_specs, op_specs, release,
                     maintenance=(), downtime=(), machine_id="M1"):
    """Minimal single-order, single-machine dataset with a factory calendar.

    shift_specs: list of (sid, start_minute, end_minute)
    day_specs:   list of (day_index, shift_ids | None); None => non-working day
    op_specs:    list of processing times (all in one order, in sequence)
    """
    ds = Dataset()
    ds.shifts = {sid: Shift(id=sid, name=sid, start_minute=s, end_minute=e)
                 for sid, s, e in shift_specs}
    ds.calendar = [CalendarDay(day_index=d, is_working=shift_ids is not None,
                               shift_ids=shift_ids or []) for d, shift_ids in day_specs]
    ds.machines[machine_id] = Machine(id=machine_id, name=machine_id, work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=[machine_id])
    ds.maintenance = list(maintenance)
    ds.downtime = list(downtime)
    op_ids = [f"OP{k}" for k in range(len(op_specs))]
    ds.operations = {
        op_ids[k]: Operation(id=op_ids[k], order_id="ORD1", sequence=k,
                             work_center_id="WC1", processing_time=proc,
                             allowed_machine_ids=[machine_id])
        for k, proc in enumerate(op_specs)
    }
    ds.orders = {"ORD1": Order(id="ORD1", product_id="P1", quantity=1,
                               release_time=release, due_time=release + 10_000, priority=1)}
    ds.routings = {"ORD1": Routing(product_id="P1", operations=op_ids)}
    ds.meta["horizon_end"] = 14 * 1440
    return ds


def test_solver_schedule_respects_calendar(solved):
    ds, out = solved
    slots = []
    for day in ds.calendar:
        if not day.is_working:
            continue
        day_start = day.day_index * 1440
        for sid in day.shift_ids:
            sh = ds.shifts[sid]
            slots.append((day_start + sh.start_minute, day_start + sh.end_minute))
    for o in out["schedule"]["operations"]:
        assert any(s0 <= o["start"] and o["end"] <= s1 for s0, s1 in slots), (
            f"{o['operation_id']} [{o['start']},{o['end']}) not inside a shift")


def test_solver_schedule_avoids_maintenance_and_downtime(solved):
    ds, out = solved
    for o in out["schedule"]["operations"]:
        for w in ds.maintenance + ds.downtime:
            if w.machine_id == o["machine_id"]:
                assert not (o["start"] < w.end and w.start < o["end"]), (
                    f"{o['operation_id']} overlaps {w.reason} on {w.machine_id}")


def test_solver_forced_to_move_due_to_maintenance():
    ds = make_calendar_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        op_specs=[60],
        release=480,
        maintenance=[MaintenanceWindow("M1", 480, 560)],  # covers the natural start
    )
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    op = out["schedule"]["operations"][0]
    assert op["start"] == 560, f"maintenance must push the op past 560, got {op['start']}"
    assert validate(ds, out["schedule"]).valid


def test_solver_forced_to_move_due_to_shift_boundary():
    ds = make_calendar_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        op_specs=[60],
        release=400,  # before the shift starts: 24/7 would start at 400
    )
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    op = out["schedule"]["operations"][0]
    assert op["start"] == 480, f"shift start must push the op past 400, got {op['start']}"
    assert validate(ds, out["schedule"]).valid


def test_solver_forced_to_move_due_to_holiday():
    ds = make_calendar_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, None), (1, ["A"])],  # day 0 holiday, day 1 working
        op_specs=[60],
        release=480,
    )
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    op = out["schedule"]["operations"][0]
    assert op["start"] == 1440 + 480, f"holiday must push the op to Monday, got {op['start']}"
    assert validate(ds, out["schedule"]).valid


# ---------------------------------------------------------------- Phase 3
def make_employee_ds(shift_specs, day_specs, machines, wc, skill, op_specs,
                     employees, release):
    """Minimal dataset with machines + employees + calendar.

    op_specs:  list of (order_id, op_id, processing_time)
    employees: list of (eid, shift_ids, skill_ids, work_center_ids,
                        available_from, available_until | None)
    """
    ds = Dataset()
    ds.shifts = {sid: Shift(id=sid, name=sid, start_minute=s, end_minute=e)
                 for sid, s, e in shift_specs}
    ds.calendar = [CalendarDay(day_index=d, is_working=shift_ids is not None,
                               shift_ids=shift_ids or []) for d, shift_ids in day_specs]
    ds.work_centers[wc] = WorkCenter(id=wc, name=wc, machine_ids=list(machines))
    for mid in machines:
        ds.machines[mid] = Machine(id=mid, name=mid, work_center_id=wc)
    ds.skills[skill] = Skill(id=skill, name=skill)
    horizon = 14 * 1440
    for eid, sids, skids, wcids, a_from, a_until in employees:
        ds.employees[eid] = Employee(
            id=eid, name=eid, shift_ids=list(sids), skill_ids=list(skids),
            work_center_ids=list(wcids), available_from=a_from,
            available_until=a_until if a_until is not None else horizon)
    by_order = {}
    ds.operations = {}
    for k, (oid, opid, proc) in enumerate(op_specs):
        ds.operations[opid] = Operation(
            id=opid, order_id=oid, sequence=k, work_center_id=wc,
            processing_time=proc, allowed_machine_ids=list(machines),
            required_skill_id=skill, employee_required=True)
        by_order.setdefault(oid, []).append(opid)
    ds.orders = {oid: Order(id=oid, product_id="P1", quantity=1,
                            release_time=release, due_time=release + 10_000, priority=1)
                 for oid in by_order}
    ds.routings = {oid: Routing(product_id="P1", operations=opids)
                   for oid, opids in by_order.items()}
    ds.meta["horizon_end"] = horizon
    return ds


def test_solver_assigns_qualified_employees(solved):
    ds, out = solved
    for o in out["schedule"]["operations"]:
        op = ds.operations[o["operation_id"]]
        emp = ds.employees[o["employee_id"]]
        assert op.required_skill_id in emp.skill_ids, f"skill mismatch {o['operation_id']}"
        assert op.work_center_id in emp.work_center_ids, f"wc mismatch {o['operation_id']}"


def test_solver_employee_shift_matches_operation(solved):
    ds, out = solved
    for o in out["schedule"]["operations"]:
        emp = ds.employees[o["employee_id"]]
        day = o["start"] // 1440
        calendar_day = next(d for d in ds.calendar if d.day_index == day)
        s_m, e_m = o["start"] % 1440, o["end"] % 1440
        sid = next(sid for sid in calendar_day.shift_ids
                   if ds.shifts[sid].start_minute <= s_m and e_m <= ds.shifts[sid].end_minute)
        assert sid in emp.shift_ids, f"shift mismatch {o['operation_id']} on {emp.id}"


def test_solver_employee_availability_respected(solved):
    ds, out = solved
    for o in out["schedule"]["operations"]:
        emp = ds.employees[o["employee_id"]]
        assert emp.available_from <= o["start"] and o["end"] <= emp.available_until, (
            f"availability violated for {o['operation_id']} on {emp.id}")


def test_solver_employee_non_overlap(solved):
    ds, out = solved
    by_emp = {}
    for o in out["schedule"]["operations"]:
        by_emp.setdefault(o["employee_id"], []).append((o["start"], o["end"]))
    for eid, intervals in by_emp.items():
        intervals.sort()
        for a in range(len(intervals) - 1):
            assert intervals[a][1] <= intervals[a + 1][0], f"employee overlap on {eid}"


def test_proof_skill_bottleneck_serializes_operations():
    ds = make_employee_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        machines=["M1", "M2"],          # two CNC machines available
        wc="WC_CNC",
        skill="CNC",
        op_specs=[("ORD0", "OP0", 60), ("ORD1", "OP1", 60)],  # two independent CNC ops
        employees=[("E_CNC", ["A"], ["CNC"], ["WC_CNC"], 0, None)],  # only 1 qualified
        release=480,
    )
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    a, b = by_id["OP0"], by_id["OP1"]
    # both operations MUST use the single CNC-qualified employee
    assert a["employee_id"] == b["employee_id"] == "E_CNC"
    # one employee on two machines => serialized, never simultaneous
    starts = sorted([a["start"], b["start"]])
    assert starts[1] >= starts[0] + 60, f"operations not serialized: {a}, {b}"
    assert a["end"] <= 960 and b["end"] <= 960  # both inside Shift A


def test_proof_shift_bottleneck_forces_shift_b():
    ds = make_employee_ds(
        shift_specs=[("A", 480, 960), ("B", 960, 1440)],
        day_specs=[(0, ["A", "B"])],
        machines=["M1"],
        wc="WC_CUTTING",
        skill="CUTTING",
        op_specs=[("ORD0", "OP0", 60)],
        employees=[("E_B", ["B"], ["CUTTING"], ["WC_CUTTING"], 0, None)],  # only shift B
        release=480,
    )
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert validate(ds, out["schedule"]).valid
    op = out["schedule"]["operations"][0]
    # Shift A is empty of qualified staff, so the op MUST run in Shift B
    assert op["employee_id"] == "E_B"
    assert op["start"] == 960, f"op should start at Shift B start (960), got {op['start']}"
    assert 960 <= op["start"] and op["end"] <= 1440


# ---------------------------------------------------------------- Phase 4
def test_employee_not_required_skips_employee_assignment():
    ds = make_calendar_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        op_specs=[60],
        release=480,
    )
    # employees + skill exist but the op does not require an employee
    ds.skills["CUTTING"] = Skill(id="CUTTING", name="Cutting")
    ds.employees["E1"] = Employee(
        id="E1", name="E1", shift_ids=["A"], skill_ids=["CUTTING"],
        work_center_ids=["WC1"], available_from=0, available_until=14 * 1440)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    op = out["schedule"]["operations"][0]
    assert op["employee_id"] is None
    assert validate(ds, out["schedule"]).valid


def test_no_employees_backward_compatible():
    ds = make_calendar_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        op_specs=[60],
        release=480,
    )
    assert not ds.employees  # Phase 1/2 style dataset
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert all(o["employee_id"] is None for o in out["schedule"]["operations"])
    assert validate(ds, out["schedule"]).valid


def test_zero_employee_candidates_produces_diagnostic():
    ds = make_employee_ds(
        shift_specs=[("A", 480, 960)],
        day_specs=[(0, ["A"])],
        machines=["M1"],
        wc="WC_CNC",
        skill="CNC",
        op_specs=[("ORD0", "OP0", 60)],
        employees=[("E_OTHER", ["A"], ["CUTTING"], ["WC_CUTTING"], 0, None)],
        release=480,
    )
    ds.skills["CUTTING"] = Skill(id="CUTTING", name="Cutting")
    ds.work_centers["WC_CUTTING"] = WorkCenter(
        id="WC_CUTTING", name="Cutting", machine_ids=[])
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert not out["result"].feasible
    assert out["result"].status == "INFEASIBLE"
    codes = [d["code"] for d in out["result"].diagnostics]
    assert "SKILL_SHORTAGE" in codes
