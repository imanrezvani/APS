"""Generator tests: determinism and structural consistency."""

from aps_engine.generator import EXTRA_HOLIDAY_DAY, SEED, generate_dataset


def test_dataset_reproducible():
    a = generate_dataset(seed=SEED)
    b = generate_dataset(seed=SEED)
    assert list(a.orders) == list(b.orders)
    assert list(a.operations) == list(b.operations)
    for oid in a.orders:
        assert a.orders[oid].release_time == b.orders[oid].release_time
        assert a.orders[oid].due_time == b.orders[oid].due_time
    for opid in a.operations:
        assert a.operations[opid].processing_time == b.operations[opid].processing_time


def test_dataset_shape():
    ds = generate_dataset(seed=SEED)
    assert len(ds.orders) == 10
    assert len(ds.products) == 5
    assert len(ds.work_centers) == 4
    assert len(ds.machines) == 8
    for order_id, routing in ds.routings.items():
        assert 3 <= len(routing.operations) <= 5


def test_dataset_consistency():
    ds = generate_dataset(seed=SEED)
    for op_id, op in ds.operations.items():
        assert op.order_id in ds.orders
        assert op.work_center_id in ds.work_centers
        for mid in op.allowed_machine_ids:
            assert mid in ds.machines
            assert ds.machines[mid].work_center_id == op.work_center_id
        assert op.allowed_machine_ids, "every operation must have a compatible machine"
        assert op.processing_time > 0
    for order_id, routing in ds.routings.items():
        assert routing.product_id == ds.orders[order_id].product_id
        assert len(routing.operations) > 0
        for k, op_id in enumerate(routing.operations):
            assert ds.operations[op_id].sequence == k
            assert ds.operations[op_id].order_id == order_id


def test_machine_assignment_is_a_real_decision():
    ds = generate_dataset(seed=SEED)
    multi = [op for op in ds.operations.values() if len(op.allowed_machine_ids) > 1]
    assert len(multi) >= len(ds.operations) - 2


# ---------------------------------------------------------------- Phase 2
def test_calendar_shape_default():
    ds = generate_dataset(seed=SEED)
    assert set(ds.shifts) == {"A", "B"}
    assert (ds.shifts["A"].start_minute, ds.shifts["A"].end_minute) == (480, 960)
    assert (ds.shifts["B"].start_minute, ds.shifts["B"].end_minute) == (960, 1440)
    assert ds.meta["n_holidays"] >= 2  # Sunday(s) + extra holiday
    for d in ds.calendar:
        if d.day_index % 7 == 6:
            assert not d.is_working, f"day {d.day_index} should be a Sunday holiday"
        elif d.day_index == EXTRA_HOLIDAY_DAY:
            assert not d.is_working, f"day {d.day_index} should be the extra holiday"
        elif d.day_index % 7 == 5:
            assert d.is_working and d.shift_ids == ["A"], "Saturday: Shift A only"
    assert ds.calendar[0].is_working and ds.calendar[0].shift_ids == ["A", "B"]


def test_maintenance_and_downtime_present():
    ds = generate_dataset(seed=SEED)
    assert len(ds.maintenance) >= 3
    assert len(ds.downtime) >= 2
    for w in ds.maintenance + ds.downtime:
        assert 0 <= w.start < w.end <= ds.meta["horizon_end"]
        assert w.machine_id in ds.machines


def test_due_dates_tight_enough_for_calendar_to_bind():
    ds = generate_dataset(seed=SEED)
    # at least one order must have a due date inside its first day, i.e. tight
    # enough that late shift releases cannot simply run 24/7 to meet it
    tight = [o for o in ds.orders.values() if o.due_time < 1440]
    assert tight, "expected at least one order with a same-day due date"


# ---------------------------------------------------------------- Phase 3
def test_employees_and_skills_present():
    ds = generate_dataset(seed=SEED)
    assert 8 <= len(ds.employees) <= 10
    assert set(ds.skills) == {"CUTTING", "EDGE_BANDING", "CNC", "ASSEMBLY"}
    cnc_qualified = [e for e in ds.employees.values() if "CNC" in e.skill_ids]
    assert len(cnc_qualified) == 2
    cnc_ops = [op for op in ds.operations.values() if op.required_skill_id == "CNC"]
    assert len(cnc_ops) >= 3
    for op in ds.operations.values():
        assert op.employee_required, f"{op.id} must require an employee"
        assert op.required_skill_id in ds.skills, f"{op.id} skill not defined"
    for e in ds.employees.values():
        assert e.shift_ids and e.skill_ids and e.work_center_ids
        assert 0 <= e.available_from < e.available_until <= ds.meta["horizon_end"]


def test_employee_contention_is_genuine():
    ds = generate_dataset(seed=SEED)
    cnc_ops = [op for op in ds.operations.values() if op.required_skill_id == "CNC"]
    cnc_qualified = [e for e in ds.employees.values() if "CNC" in e.skill_ids]
    assert len(cnc_ops) > len(cnc_qualified), "CNC work must exceed CNC staff"
    # employees spread across shifts
    shifts_used = {sid for e in ds.employees.values() for sid in e.shift_ids}
    assert shifts_used == {"A", "B"}
