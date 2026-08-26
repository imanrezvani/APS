"""Phase 5 Part 3 - independent material validation tests.

``validate()`` re-derives material consumption from the schedule and the BOMs
(never from the CP-SAT model): each order commits its full BOM material demand
for the whole duration of its production chain, and the peak committed
working stock of a material at any instant must not exceed on-hand inventory.
Over-committed materials yield a MATERIAL_VIOLATION carrying material_id /
required / available / shortage details.

These tests exercise only the public validator API with hand-built datasets
and schedules, proving the check is independent of the solver:
  1. a serialized (material-valid) schedule passes,
  2. an overlapping schedule that over-commits stock is flagged,
  3. consumption is time-phased cumulative (reuse between back-to-back orders
     is allowed, an instant of over-commit is not),
  4. the material-feasible generator variant validates cleanly.
"""

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    Dataset,
    Machine,
    Material,
    MaterialInventory,
    Operation,
    Order,
    Routing,
    WorkCenter,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import MATERIAL_VIOLATION, validate

PARAMS = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)


def _material_ds(on_hand):
    """Two parallel orders (separate machines) sharing one material.

    Each order produces 10 units of P1 and P1 needs 1.0 unit of M per unit,
    so each order demands 10.0 of M. No calendar/employees: 24/7, freely
    placeable within [480, 2000).
    """
    ds = Dataset()
    ds.meta["horizon_end"] = 2000
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1", "M2"])
    ds.machines = {
        "M1": Machine(id="M1", name="M1", work_center_id="WC1"),
        "M2": Machine(id="M2", name="M2", work_center_id="WC1"),
    }
    ds.operations = {
        "OP1": Operation(id="OP1", order_id="ORD1", sequence=0, work_center_id="WC1",
                         processing_time=60, allowed_machine_ids=["M1"]),
        "OP2": Operation(id="OP2", order_id="ORD2", sequence=0, work_center_id="WC1",
                         processing_time=60, allowed_machine_ids=["M2"]),
    }
    ds.orders = {
        "ORD1": Order(id="ORD1", product_id="P1", quantity=10, release_time=480,
                      due_time=2000, priority=1),
        "ORD2": Order(id="ORD2", product_id="P1", quantity=10, release_time=480,
                      due_time=2000, priority=1),
    }
    ds.routings = {
        "ORD1": Routing(product_id="P1", operations=["OP1"]),
        "ORD2": Routing(product_id="P1", operations=["OP2"]),
    }
    ds.materials["M"] = Material(id="M", name="M")
    ds.boms["P1"] = BOM(product_id="P1", items=[BomItem(material_id="M", quantity_per_unit=1.0)])
    ds.inventory["M"] = MaterialInventory(material_id="M", on_hand=on_hand)
    return ds


def _schedule(ds, op_times):
    """Schedule dict for the two-order dataset; op_times maps op -> (s, e)."""
    operations = [
        {"operation_id": op_id, "order_id": ds.operations[op_id].order_id,
         "machine_id": ds.operations[op_id].allowed_machine_ids[0],
         "employee_id": None, "start": s, "end": e}
        for op_id, (s, e) in op_times.items()
    ]
    orders = []
    for oid in sorted(ds.orders):
        last = ds.routings[oid].operations[-1]
        completion = op_times[last][1]
        due = ds.orders[oid].due_time
        orders.append({"order_id": oid, "completion_time": completion,
                       "due_time": due, "tardiness": max(0, completion - due)})
    return {"operations": operations, "orders": orders}


def _material_violations(ds, schedule):
    return [v for v in validate(ds, schedule).violations
            if v.code == MATERIAL_VIOLATION]


# ---------------------------------------------- 1. valid material schedule
def test_serialized_schedule_passes_material_validation():
    # Both orders run back-to-back: peak committed is 10 <= 15 on-hand.
    ds = _material_ds(on_hand=15.0)
    schedule = _schedule(ds, {"OP1": (480, 540), "OP2": (540, 600)})
    result = validate(ds, schedule)
    assert result.valid, [v.message for v in result.violations]
    assert _material_violations(ds, schedule) == []


# ----------------------------------------- 2. material violation detected
def test_overlapping_schedule_flags_material_violation():
    # Both orders in production together commit 20.0 > 15.0 on-hand.
    ds = _material_ds(on_hand=15.0)
    schedule = _schedule(ds, {"OP1": (480, 540), "OP2": (480, 540)})
    result = validate(ds, schedule)
    violations = _material_violations(ds, schedule)
    assert len(violations) == 1
    v = violations[0]
    assert v.entity == "M"
    assert v.details == {"material_id": "M", "required": 20.0,
                         "available": 15.0, "shortage": 5.0}
    assert "committed 20.0 of M" in v.message
    assert "only 15.0 on-hand" in v.message
    assert "(short 5.0)" in v.message


# ------------------------------- 3. time-phased cumulative consumption
def test_consumption_is_cumulative_not_total():
    # Back-to-back orders consume 20.0 in total but never more than 10.0 at
    # once, so the schedule is valid: stock is reused between orders.
    ds = _material_ds(on_hand=15.0)
    schedule = _schedule(ds, {"OP1": (480, 540), "OP2": (540, 600)})
    assert validate(ds, schedule).valid
    # A single instant of overlap commits 20.0 and must be flagged even when
    # total consumption is identical.
    partial = _schedule(ds, {"OP1": (480, 540), "OP2": (500, 560)})
    violations = _material_violations(ds, partial)
    assert len(violations) == 1
    assert violations[0].details["required"] == 20.0
    assert violations[0].details["shortage"] == 5.0


def test_peak_equals_sum_when_fully_overlapping():
    ds = _material_ds(on_hand=15.0)
    schedule = _schedule(ds, {"OP1": (480, 540), "OP2": (480, 540)})
    assert _material_violations(ds, schedule)[0].details["required"] == 20.0


# ------------------------------------------ 4. feasible generator variant
def test_feasible_generator_variant_validates_cleanly():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert out["result"].status == "OPTIMAL"
    assert out["result"].objective_value == 39.0
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
    assert len(result.violations) == 0


def test_feasible_variant_has_no_material_violations():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert _material_violations(ds, out["schedule"]) == []
