"""Phase 5 Part 1 - aggregate material availability constraint tests.

The CP-SAT model is forced infeasible when the aggregated material demand of
the whole order book exceeds on-hand inventory, and build_diagnostics emits a
MATERIAL_SHORTAGE per short material (material_id, required, available,
shortage). Material-feasible datasets are unaffected and still solve to
OPTIMAL 39.0. Pure aggregate check: no consumption, reservation, or
allocation.
"""

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    CalendarDay,
    Dataset,
    Machine,
    Operation,
    Order,
    Routing,
    Shift,
    WorkCenter,
)
from aps_engine.solver.diagnostics import MATERIAL_SHORTAGE
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate

PARAMS = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)


# ------------------------------------------------------- material-short dataset
def test_material_short_dataset_is_infeasible():
    ds = generate_dataset()
    out = solve(ds, PARAMS)
    assert out["result"].status == "INFEASIBLE"
    assert not out["result"].feasible


def test_material_short_diagnostics_cover_all_short_materials():
    ds = generate_dataset()
    feasibility = ds.order_book_material_feasibility()
    out = solve(ds, PARAMS)
    material_diags = [d for d in out["result"].diagnostics
                      if d["code"] == MATERIAL_SHORTAGE]
    assert {d["resource_id"] for d in material_diags} == set(feasibility.shortages)


def test_material_shortage_diagnostic_values():
    ds = generate_dataset()
    out = solve(ds, PARAMS)
    diag = next(d for d in out["result"].diagnostics
                if d["code"] == MATERIAL_SHORTAGE and d["resource_id"] == "M_BOARD")
    assert diag["resource_type"] == "material"
    # required=389.0, available=120.0, shortage=269.0 for the default dataset
    assert "requires 389.0 units" in diag["reason"]
    assert "only 120.0 are on-hand" in diag["reason"]
    assert "(short 269.0)" in diag["reason"]


# ------------------------------------------------- material-feasible dataset
def test_material_feasible_dataset_optimal_39():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert out["result"].status == "OPTIMAL"
    assert out["result"].objective_value == 39.0
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
    assert len(result.violations) == 0


def test_material_feasible_dataset_has_no_material_diagnostics():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, PARAMS)
    assert [d for d in out["result"].diagnostics
            if d["code"] == MATERIAL_SHORTAGE] == []


# -------------------------------------------------- datasets without materials
def test_material_free_dataset_unaffected():
    ds = Dataset()
    ds.shifts["A"] = Shift(id="A", name="A", start_minute=480, end_minute=960)
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.operations["OP1"] = Operation(
        id="OP1", order_id="ORD1", sequence=0, work_center_id="WC1",
        processing_time=60, allowed_machine_ids=["M1"])
    ds.orders["ORD1"] = Order(id="ORD1", product_id="P1", quantity=1,
                              release_time=480, due_time=1000, priority=1)
    ds.routings["ORD1"] = Routing(product_id="P1", operations=["OP1"])
    ds.meta["horizon_end"] = 14 * 1440
    out = solve(ds, PARAMS)
    assert out["result"].feasible
    assert out["result"].diagnostics == []


# ------------------------------------------------------------ read-only check
def test_material_constraint_does_not_mutate_dataset():
    ds = generate_dataset()
    inventory_before = {mid: inv.on_hand for mid, inv in ds.inventory.items()}
    boms_before = dict(ds.boms)
    solve(ds, PARAMS)
    assert {mid: inv.on_hand for mid, inv in ds.inventory.items()} == inventory_before
    assert ds.boms == boms_before
