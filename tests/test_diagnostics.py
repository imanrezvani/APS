"""Infeasibility diagnostics tests (Phase 4 Part 2).

Each scenario builds a minimal dataset that CP-SAT rejects as INFEASIBLE and
asserts that the solver result carries the expected diagnostic category.
"""

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    CalendarDay,
    Dataset,
    Employee,
    Machine,
    Operation,
    Order,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)
from aps_engine.solver.diagnostics import (
    CALENDAR_CONFLICT,
    EMPLOYEE_AVAILABILITY,
    EMPLOYEE_SHORTAGE,
    GLOBAL_SCHEDULING_CONFLICT,
    HORIZON_CONFLICT,
    MACHINE_SHORTAGE,
    PRECEDENCE_CONFLICT,
    SKILL_SHORTAGE,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve


def _make_ds(shifts, days, machine_ids, ops, release, horizon=1440,
             skill_id="SK1", employees=()):
    """Minimal dataset.

    shifts:   list of (sid, start_minute, end_minute)
    days:     list of (day_index, shift_ids | None); None => non-working
    ops:      list of (order_id, op_id, proc, employee_required,
                       allowed_machine_ids | None)
    """
    ds = Dataset()
    ds.shifts = {sid: Shift(id=sid, name=sid, start_minute=s, end_minute=e)
                 for sid, s, e in shifts}
    ds.calendar = [CalendarDay(day_index=d, is_working=shift_ids is not None,
                               shift_ids=shift_ids or [])
                   for d, shift_ids in days]
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1",
                                        machine_ids=list(machine_ids))
    for mid in machine_ids:
        ds.machines[mid] = Machine(id=mid, name=mid, work_center_id="WC1")
    ds.skills[skill_id] = Skill(id=skill_id, name=skill_id)
    for eid, sids, skids, wcids, a_from, a_until in employees:
        ds.employees[eid] = Employee(
            id=eid, name=eid, shift_ids=list(sids), skill_ids=list(skids),
            work_center_ids=list(wcids), available_from=a_from,
            available_until=a_until)
    by_order = {}
    ds.operations = {}
    for k, (oid, opid, proc, emp_required, allowed) in enumerate(ops):
        if allowed is None:
            allowed = list(machine_ids)
        ds.operations[opid] = Operation(
            id=opid, order_id=oid, sequence=k, work_center_id="WC1",
            processing_time=proc, allowed_machine_ids=list(allowed),
            required_skill_id=skill_id if emp_required else "",
            employee_required=emp_required)
        by_order.setdefault(oid, []).append(opid)
    ds.orders = {oid: Order(id=oid, product_id="P1", quantity=1,
                            release_time=release, due_time=release + 10_000,
                            priority=1)
                 for oid in by_order}
    ds.routings = {oid: Routing(product_id="P1", operations=opids)
                   for oid, opids in by_order.items()}
    ds.meta["horizon_end"] = horizon
    return ds


PARAMS = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)


def _codes(out):
    return [d["code"] for d in out["result"].diagnostics]


def test_feasible_solution_has_empty_diagnostics():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert out["result"].feasible
    assert out["result"].diagnostics == []


def test_a_no_machine_machine_shortage():
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, False, [])],  # zero allowed machines
        release=480)
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert out["result"].status == "INFEASIBLE"
    assert MACHINE_SHORTAGE in _codes(out)


def test_b_no_employee_employee_shortage():
    # skilled + authorized employee exists, but works shift B while the
    # calendar only offers shift A -> no employee can ever work the op
    ds = _make_ds(
        shifts=[("A", 480, 960), ("B", 960, 1440)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, True, None)],
        release=480,
        employees=[("E1", ["B"], ["SK1"], ["WC1"], 0, 1440)])
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert EMPLOYEE_SHORTAGE in _codes(out)


def test_c_no_qualified_skill_skill_shortage():
    # skill SK1 is defined, but the only employee holds SK2
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, True, None)],
        release=480)
    ds.skills["SK2"] = Skill(id="SK2", name="SK2")
    ds.employees["E1"] = Employee(
        id="E1", name="E1", shift_ids=["A"], skill_ids=["SK2"],
        work_center_ids=["WC1"], available_from=0, available_until=1440)
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert SKILL_SHORTAGE in _codes(out)


def test_d_employee_unavailable_employee_availability():
    # employee availability window (40) shorter than processing time (60)
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, True, None)],
        release=480,
        employees=[("E1", ["A"], ["SK1"], ["WC1"], 0, 40)])
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert EMPLOYEE_AVAILABILITY in _codes(out)


def test_e_impossible_calendar_calendar_conflict():
    # only working slot is 60 minutes long; op needs 70 -> fits no slot
    ds = _make_ds(
        shifts=[("A", 480, 540)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 70, False, None)],
        release=480)
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert CALENDAR_CONFLICT in _codes(out)


def test_f_impossible_horizon_horizon_conflict():
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, False, None)],
        release=2000, horizon=1440)  # release beyond horizon end
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert HORIZON_CONFLICT in _codes(out)


def test_g_global_conflict_global_scheduling_conflict():
    # both ops individually fit a 480-minute slot and have valid machines,
    # but two 400-minute ops on one machine cannot share a 480-minute slot
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None),
             ("ORD2", "OP2", 400, False, None)],
        release=480)
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert GLOBAL_SCHEDULING_CONFLICT in _codes(out)
    assert len(out["result"].diagnostics) == 1


def test_h_precedence_conflict_detected():
    # chain of two 40-minute ops on one machine inside a 60-minute slot
    ds = _make_ds(
        shifts=[("A", 480, 540)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 40, False, None),
             ("ORD1", "OP2", 40, False, None)],
        release=480)
    out = solve(ds, PARAMS)
    assert not out["result"].feasible
    assert PRECEDENCE_CONFLICT in _codes(out)


def test_diagnostics_include_resource_context():
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, True, None)],
        release=480,
        employees=[("E1", ["A"], ["SK1"], ["WC1"], 0, 40)])
    out = solve(ds, PARAMS)
    diag = next(d for d in out["result"].diagnostics
                if d["code"] == EMPLOYEE_AVAILABILITY)
    assert diag["operation_id"] == "OP1"
    assert diag["order_id"] == "ORD1"
    assert diag["resource_type"] == "employee"
    assert "E1" in diag["resource_id"]
    assert diag["reason"]
