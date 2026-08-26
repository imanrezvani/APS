"""Phase 5 Part 2 - time-phased material consumption tests.

The material constraint in ``solver/model.py`` is a cumulative (working
stock) constraint: an order commits its full BOM material demand from the
start of its first operation to the end of its last operation, and the
committed quantity of each material may never exceed the on-hand inventory
at any instant. These tests prove:

  1. sufficient inventory -> the schedule stays feasible (OPTIMAL 39.0),
  2. scarce material     -> competing orders cannot over-consume: they are
                            serialized, and when serialization is impossible
                            the model is INFEASIBLE,
  3. availability        -> changing on-hand stock actually changes solver
                            timing / assignment,
  4. cumulative          -> the committed working stock derived from any
                            schedule never exceeds on-hand for any material.

Consumption happens only inside the CP-SAT model; the Dataset is never
mutated (no reservation or allocation).
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
from aps_engine.validation.validator import validate

PARAMS = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)


def make_material_ds(*, processing_time, on_hand, release, due_time, horizon_end):
    """Two parallel orders (separate machines) sharing one scarce material.

    Each order produces 10 units of P1, and P1 needs 1.0 unit of material M
    per unit, so each order demands 10.0 of M. With on_hand = 15 the two
    orders must never be in production simultaneously.
    """
    ds = Dataset()
    ds.meta["horizon_end"] = horizon_end
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1", "M2"])
    ds.machines = {
        "M1": Machine(id="M1", name="M1", work_center_id="WC1"),
        "M2": Machine(id="M2", name="M2", work_center_id="WC1"),
    }
    ds.operations = {
        "OP1": Operation(id="OP1", order_id="ORD1", sequence=0, work_center_id="WC1",
                         processing_time=processing_time, allowed_machine_ids=["M1"]),
        "OP2": Operation(id="OP2", order_id="ORD2", sequence=0, work_center_id="WC1",
                         processing_time=processing_time, allowed_machine_ids=["M2"]),
    }
    ds.orders = {
        "ORD1": Order(id="ORD1", product_id="P1", quantity=10, release_time=release,
                      due_time=due_time, priority=1),
        "ORD2": Order(id="ORD2", product_id="P1", quantity=10, release_time=release,
                      due_time=due_time, priority=1),
    }
    ds.routings = {
        "ORD1": Routing(product_id="P1", operations=["OP1"]),
        "ORD2": Routing(product_id="P1", operations=["OP2"]),
    }
    ds.materials["M"] = Material(id="M", name="M")
    ds.boms["P1"] = BOM(product_id="P1", items=[BomItem(material_id="M", quantity_per_unit=1.0)])
    ds.inventory["M"] = MaterialInventory(material_id="M", on_hand=on_hand)
    return ds


def order_intervals(ds, schedule):
    """Order production-chain spans (first-op start, last-op end)."""
    ops = {o["operation_id"]: o for o in schedule["operations"]}
    spans = {}
    for order_id, routing in ds.routings.items():
        first, last = routing.operations[0], routing.operations[-1]
        spans[order_id] = (ops[first]["start"], ops[last]["end"])
    return spans


def max_committed(ds, schedule):
    """Per material, the peak committed working stock over the schedule."""
    spans = order_intervals(ds, schedule)
    rows = {mid: [] for mid in ds.materials}
    for order_id, (start, end) in spans.items():
        for mid, qty in ds.material_demand(order_id).items():
            if qty > 0:
                rows[mid].append((start, end, qty))
    peaks = {}
    for mid, intervals in rows.items():
        events = sorted({t for (s, e, _) in intervals for t in (s, e)})
        peak = 0.0
        for t in events:
            peak = max(peak, sum(q for s, e, q in intervals if s <= t < e))
        peaks[mid] = peak
    return peaks


# ------------------------------------------------------ 1. sufficient inventory
def test_sufficient_inventory_schedule_is_feasible():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert out["result"].status == "OPTIMAL"
    assert out["result"].objective_value == 39.0
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
    assert len(result.violations) == 0


# ----------------------------------------------------- 2. scarce material
def test_scarce_material_serializes_competing_orders():
    # Two orders each demand 10.0 of M, only 15 on-hand: they cannot be in
    # production simultaneously (that would commit 20.0 > 15.0), so any
    # feasible schedule must serialize them.
    ds = make_material_ds(processing_time=60, on_hand=15.0,
                          release=480, due_time=2000, horizon_end=2000)
    out = solve(ds, PARAMS)
    assert out["result"].feasible
    s1, e1 = order_intervals(ds, out["schedule"])["ORD1"]
    s2, e2 = order_intervals(ds, out["schedule"])["ORD2"]
    assert e1 <= s2 or e2 <= s1


def test_scarce_material_impossible_serialization_is_infeasible():
    # 900-min chains on both machines cannot be serialized inside the window
    # [480, 1500), and any overlap commits 20.0 > 15.0 on-hand => INFEASIBLE.
    ds = make_material_ds(processing_time=900, on_hand=15.0,
                          release=480, due_time=2000, horizon_end=1500)
    out = solve(ds, PARAMS)
    assert out["result"].status == "INFEASIBLE"


# --------------------------------------------------- 3. availability / timing
def test_material_availability_changes_solver_timing():
    # due 540 forces start at 480 to reach tardiness 0; with on_hand 20 both
    # orders run in parallel, with on_hand 15 they must be staggered.
    scarce = make_material_ds(processing_time=60, on_hand=15.0,
                              release=480, due_time=540, horizon_end=2000)
    ample = make_material_ds(processing_time=60, on_hand=20.0,
                             release=480, due_time=540, horizon_end=2000)
    out_scarce = solve(scarce, PARAMS)
    out_ample = solve(ample, PARAMS)
    assert out_scarce["result"].feasible
    assert out_ample["result"].feasible
    a1, b1 = order_intervals(scarce, out_scarce["schedule"])["ORD1"]
    a2, b2 = order_intervals(scarce, out_scarce["schedule"])["ORD2"]
    assert b1 <= a2 or b2 <= a1  # scarce: staggered
    s1, e1 = order_intervals(ample, out_ample["schedule"])["ORD1"]
    s2, e2 = order_intervals(ample, out_ample["schedule"])["ORD2"]
    assert s1 == s2 == 480  # ample: both at release, in parallel
    assert out_scarce["result"].objective_value > out_ample["result"].objective_value


# ------------------------------------------- 4. cumulative never exceeds stock
def test_committed_material_never_exceeds_on_hand():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert out["result"].feasible
    peaks = max_committed(ds, out["schedule"])
    assert set(peaks) == set(ds.materials)
    for mid, peak in peaks.items():
        assert peak <= ds.inventory[mid].on_hand + 1e-9, mid


def test_scarce_material_schedule_never_over_consumes():
    ds = make_material_ds(processing_time=60, on_hand=15.0,
                          release=480, due_time=2000, horizon_end=2000)
    out = solve(ds, PARAMS)
    assert out["result"].feasible
    assert max_committed(ds, out["schedule"])["M"] <= 15.0 + 1e-9


# ------------------------------------------------------------- read-only check
def test_time_phased_constraint_does_not_mutate_dataset():
    ds = generate_dataset()
    inventory_before = {mid: inv.on_hand for mid, inv in ds.inventory.items()}
    solve(ds, PARAMS)
    assert {mid: inv.on_hand for mid, inv in ds.inventory.items()} == inventory_before
