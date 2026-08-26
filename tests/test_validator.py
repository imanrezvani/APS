"""Validator tests.

TEST 1: a valid schedule passes validation.
TEST 2: artificial machine overlap is detected.
TEST 3: artificial precedence violation is detected.
TEST 4: artificial machine incompatibility is detected.
TEST 5: artificial release-time violation is detected.
"""

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.validation.validator import validate


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


def _unavailable(ds, machine):
    return [(w.start, w.end)
            for w in list(ds.maintenance) + list(ds.downtime)
            if w.machine_id == machine]


def _eligible_employees(ds, op):
    return [e for e in ds.employees.values()
            if op.required_skill_id in e.skill_ids
            and op.work_center_id in e.work_center_ids
            and e.available_until - e.available_from >= op.processing_time]


def make_valid_schedule(ds):
    """Deterministic constructive schedule: valid by construction.

    Each operation is placed on its first allowed machine and one eligible
    employee, never overlapping that machine (or its maintenance/downtime
    windows), never before release, never before its predecessor, always
    inside a working shift, and with a setup gap after the machine's previous
    activity (setup_time of the operation being placed).
    """
    machine_free = {mid: 0 for mid in ds.machines}
    machine_used = {mid: False for mid in ds.machines}
    employee_free = {eid: 0 for eid in ds.employees}
    starts, ends, employees = {}, {}, {}
    order_ids = sorted(ds.orders)
    for oid in order_ids:
        prev_end = 0
        for op_id in ds.routings[oid].operations:
            op = ds.operations[op_id]
            machine = op.allowed_machine_ids[0]
            want = max(machine_free[machine], ds.orders[oid].release_time, prev_end)
            if machine_used[machine]:
                want = max(want, machine_free[machine] + op.setup_time)
            eligible = _eligible_employees(ds, op)
            blocked = _unavailable(ds, machine)
            start = end = eid = None
            for s0, s1, sid in _working_slots(ds):
                if s1 - s0 < op.processing_time:
                    continue
                cand = max(want, s0)
                if cand + op.processing_time > s1:
                    continue
                # the machine is occupied by the extended interval
                # [start - setup, end], so maintenance/downtime must not
                # overlap it
                ext_start = cand - op.setup_time
                if any(ext_start < w1 and w0 < cand + op.processing_time
                       for w0, w1 in blocked):
                    continue
                for e in eligible:
                    if sid not in e.shift_ids:
                        continue
                    if not (e.available_from <= cand and
                            cand + op.processing_time <= e.available_until):
                        continue
                    if cand < employee_free[e.id]:
                        continue
                    start, end, eid = cand, cand + op.processing_time, e.id
                    break
                if eid is not None:
                    break
            if start is None:  # no calendar / employees -> free placement
                start = want
                end = start + op.processing_time
                eid = next((e.id for e in eligible), None)
            starts[op_id], ends[op_id], employees[op_id] = start, end, eid
            machine_free[machine] = end
            machine_used[machine] = True
            if eid:
                employee_free[eid] = end
            prev_end = end
    operations = [
        {"operation_id": op_id, "order_id": ds.operations[op_id].order_id,
         "machine_id": ds.operations[op_id].allowed_machine_ids[0],
         "employee_id": employees.get(op_id),
         "start": starts[op_id], "end": ends[op_id]}
        for op_id in ds.operations
    ]
    orders = []
    for oid, order in ds.orders.items():
        last = ds.routings[oid].operations[-1]
        completion = ends[last]
        orders.append({"order_id": oid, "completion_time": completion,
                       "due_time": order.due_time,
                       "tardiness": max(0, completion - order.due_time)})
    return {"operations": operations, "orders": orders}


@pytest.fixture(scope="module")
def ds():
    # The default dataset is material-short (Phase 5): no schedule can pass
    # the time-phased material check. The material-feasible variant raises
    # on-hand inventory to exactly cover the order book, so the constructive
    # schedules used here stay material-valid while exercising every other
    # validator check.
    return generate_dataset(material_feasible=True)


@pytest.fixture(scope="module")
def valid_schedule(ds):
    return make_valid_schedule(ds)


def test_valid_schedule_passes_validation(ds, valid_schedule):
    result = validate(ds, valid_schedule)
    assert result.valid, [v.message for v in result.violations]


def test_machine_overlap_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    # shift the second-scheduled operation on its machine to overlap the first
    ops = sorted(broken["operations"], key=lambda o: o["start"])
    by_machine = {}
    for o in ops:
        by_machine.setdefault(o["machine_id"], []).append(o)
    for mid, group in by_machine.items():
        if len(group) >= 2:
            a, b = group[0], group[1]
            b["start"] = a["start"] + 1
            b["end"] = b["start"] + ds.operations[b["operation_id"]].processing_time
            break
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "MACHINE_OVERLAP" for v in result.violations)


def test_precedence_violation_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    # make the 2nd operation of the first order start before the 1st ends
    oid = sorted(ds.orders)[0]
    ops = ds.routings[oid].operations
    by_id = {o["operation_id"]: o for o in broken["operations"]}
    by_id[ops[1]]["start"] = by_id[ops[0]]["end"] - 5
    by_id[ops[1]]["end"] = by_id[ops[1]]["start"] + ds.operations[ops[1]].processing_time
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "PRECEDENCE" for v in result.violations)


def test_machine_incompatibility_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]
    op_id = op["operation_id"]
    op["machine_id"] = "NOT_A_MACHINE"
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "MACHINE_COMPAT" and v.entity == op_id for v in result.violations)


def test_release_time_violation_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    oid = sorted(ds.orders)[0]
    first = ds.routings[oid].operations[0]
    release = ds.orders[oid].release_time
    by_id = {o["operation_id"]: o for o in broken["operations"]}
    assert by_id[first]["start"] >= release  # sanity: originally valid
    by_id[first]["start"] = release - 1
    by_id[first]["end"] = by_id[first]["start"] + ds.operations[first].processing_time
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "RELEASE_TIME" for v in result.violations)


def test_completion_tardiness_mismatch_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    broken["orders"][0]["completion_time"] += 999
    result = validate(ds, broken)
    assert not result.valid
    codes = {v.code for v in result.violations}
    assert "COMPLETION_MISMATCH" in codes


# ---------------------------------------------------------------- Phase 2
def test_op_on_holiday_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]
    proc = ds.operations[op["operation_id"]].processing_time
    start = 6 * 1440 + 600  # Sunday 10:00 -> holiday
    op["start"], op["end"] = start, start + proc
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "HOLIDAY" and v.entity == op["operation_id"]
               for v in result.violations)


def test_op_crossing_shift_boundary_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]
    proc = ds.operations[op["operation_id"]].processing_time
    op["start"], op["end"] = 950, 950 + proc  # spans 16:00 boundary of day 0
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "SHIFT_BOUNDARY" and v.entity == op["operation_id"]
               for v in result.violations)


def test_op_outside_any_shift_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]
    proc = ds.operations[op["operation_id"]].processing_time
    start = 1440 + 60  # Tuesday 01:00 -> in the overnight gap, no shift
    op["start"], op["end"] = start, start + proc
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "SHIFT_BOUNDARY" and v.entity == op["operation_id"]
               for v in result.violations)


def test_op_overlapping_maintenance_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    w = ds.maintenance[0]
    op = next(o for o in broken["operations"]
              if w.machine_id in ds.operations[o["operation_id"]].allowed_machine_ids)
    proc = ds.operations[op["operation_id"]].processing_time
    op["machine_id"] = w.machine_id
    op["start"], op["end"] = w.start + 1, w.start + 1 + proc
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "MAINTENANCE" and v.entity == op["operation_id"]
               for v in result.violations)


def test_op_overlapping_downtime_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    w = ds.downtime[0]
    op = next(o for o in broken["operations"]
              if w.machine_id in ds.operations[o["operation_id"]].allowed_machine_ids)
    proc = ds.operations[op["operation_id"]].processing_time
    op["machine_id"] = w.machine_id
    op["start"], op["end"] = w.start + 1, w.start + 1 + proc
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "DOWNTIME" and v.entity == op["operation_id"]
               for v in result.violations)


# ---------------------------------------------------------------- Phase 3
def test_employee_missing_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]
    op["employee_id"] = None
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_MISSING" and v.entity == op["operation_id"]
               for v in result.violations)


def test_employee_wrong_skill_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]  # CUTTING op
    op["employee_id"] = "E_CNC_A"  # lacks CUTTING skill
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_SKILL" and v.entity == op["operation_id"]
               for v in result.violations)


def test_employee_wrong_work_center_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    op = broken["operations"][0]  # WC_CUTTING op
    op["employee_id"] = "E_ASM_A"  # not authorized for WC_CUTTING
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_WORK_CENTER" and v.entity == op["operation_id"]
               for v in result.violations)


def test_employee_wrong_shift_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    # CNC ops land in Shift B in the constructive schedule; E_CNC_A works
    # only Shift A, so assigning it to a Shift B op is a shift violation.
    target = next(
        o for o in broken["operations"]
        if ds.operations[o["operation_id"]].required_skill_id == "CNC"
        and o["start"] % 1440 >= 960)
    target["employee_id"] = "E_CNC_A"  # Shift A employee on a Shift B op
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_SHIFT" and v.entity == target["operation_id"]
               for v in result.violations)


def test_employee_overlap_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    by_emp = {}
    for o in broken["operations"]:
        by_emp.setdefault(o["employee_id"], []).append(o)
    emp = max(by_emp, key=lambda e: len(by_emp[e]))
    group = sorted(by_emp[emp], key=lambda o: o["start"])
    a, b = group[0], group[1]
    proc = ds.operations[b["operation_id"]].processing_time
    b["start"], b["end"] = a["start"] + 1, a["start"] + 1 + proc
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_OVERLAP" for v in result.violations)


def test_employee_availability_detected(ds, valid_schedule):
    broken = {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }
    # E_EDGE_B is unavailable before Tuesday (absolute minute 1440)
    target = next(
        o for o in broken["operations"]
        if ds.operations[o["operation_id"]].required_skill_id == "EDGE_BANDING"
        and o["start"] < 1440)
    target["employee_id"] = "E_EDGE_B"
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "EMPLOYEE_AVAILABILITY" and v.entity == target["operation_id"]
               for v in result.violations)


# ---------------------------------------------------------------- Phase 4
# coverage: the remaining validator codes
def _copy_schedule(valid_schedule):
    return {
        "operations": [dict(o) for o in valid_schedule["operations"]],
        "orders": [dict(o) for o in valid_schedule["orders"]],
    }


def test_unknown_employee_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    broken["operations"][0]["employee_id"] = "NOBODY"
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "UNKNOWN_EMPLOYEE" for v in result.violations)


def test_tardiness_mismatch_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    broken["orders"][0]["tardiness"] += 5
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "TARDINESS_MISMATCH" for v in result.violations)


def test_machine_missing_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    removed = broken["operations"][0]["operation_id"]
    broken["operations"] = [o for o in broken["operations"]
                            if o["operation_id"] != removed]
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "MACHINE_MISSING" and v.entity == removed
               for v in result.violations)


def test_duplicate_operation_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    broken["operations"].append(dict(broken["operations"][0]))
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "DUPLICATE_OPERATION" for v in result.violations)


def test_unknown_operation_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    op = dict(broken["operations"][0])
    op["operation_id"] = "OP_NOPE"
    op["order_id"] = "ORD_NOPE"
    broken["operations"].append(op)
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "UNKNOWN_OPERATION" for v in result.violations)


def test_missing_order_detected(ds, valid_schedule):
    broken = _copy_schedule(valid_schedule)
    missing = broken["orders"][0]["order_id"]
    broken["orders"] = [o for o in broken["orders"] if o["order_id"] != missing]
    result = validate(ds, broken)
    assert not result.valid
    assert any(v.code == "MISSING_ORDER" and v.entity == missing
               for v in result.violations)


def test_no_schedule_detected(ds):
    result = validate(ds, None)
    assert not result.valid
    assert any(v.code == "NO_SCHEDULE" for v in result.violations)
