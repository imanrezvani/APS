"""Phase 4.7 Part 2 - material-feasible dataset scenario tests.

The default dataset is intentionally material-infeasible at the order-book
level. ``generate_dataset(material_feasible=True)`` raises inventory to
exactly cover the entire order book while keeping BOMs, products, orders, and
all scheduling data unchanged. No inventory consumption, reservation, or
allocation is involved.
"""

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import Dataset
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate

_SCHEDULING_FIELDS = [
    "products",
    "boms",
    "orders",
    "operations",
    "routings",
    "work_centers",
    "machines",
    "skills",
    "employees",
    "shifts",
    "calendar",
    "maintenance",
    "downtime",
    "setup_matrix",
    "materials",
]


def _assert_scheduling_data_unchanged(feasible: Dataset) -> None:
    default = generate_dataset()
    for field in _SCHEDULING_FIELDS:
        assert getattr(feasible, field) == getattr(default, field), field


def _order_book_demand(ds: Dataset):
    demand = {}
    for order in ds.orders.values():
        for mid, qty in ds.material_requirements(order.product_id, order.quantity).items():
            demand[mid] = demand.get(mid, 0.0) + qty
    return demand


# ------------------------------------------------------------------ scenarios
def test_default_dataset_is_material_infeasible():
    ds = generate_dataset()
    assert ds.meta["material_feasible"] is False
    assert ds.order_book_material_feasibility().feasible is False


def test_feasible_variant_is_material_feasible():
    ds = generate_dataset(material_feasible=True)
    assert ds.meta["material_feasible"] is True
    assert ds.order_book_material_feasibility().feasible is True


def test_feasible_variant_keeps_default_inventory_unchanged():
    # Feasible generation must not mutate the default INVENTORY constants.
    default = generate_dataset()
    assert default.order_book_material_feasibility().feasible is False


def test_feasible_variant_covers_exact_order_book_demand():
    ds = generate_dataset(material_feasible=True)
    for mid, req in _order_book_demand(ds).items():
        assert ds.inventory[mid].on_hand == req
    assert ds.order_book_material_feasibility().shortages == {}


# ------------------------------------------------------------ scheduling data
def test_feasible_variant_keeps_boms_products_orders():
    feasible = generate_dataset(material_feasible=True)
    _assert_scheduling_data_unchanged(feasible)


def test_feasible_variant_differs_only_in_inventory():
    default = generate_dataset()
    feasible = generate_dataset(material_feasible=True)
    assert feasible.inventory != default.inventory


# ---------------------------------------------------------------- determinism
def test_feasible_variant_is_deterministic():
    for _ in range(3):
        a = generate_dataset(material_feasible=True, seed=SEED)
        b = generate_dataset(material_feasible=True, seed=SEED)
        assert a.inventory == b.inventory
        assert a.orders == b.orders


# --------------------------------------------------------------------- solver
def test_feasible_variant_solver_status_and_objective():
    ds = generate_dataset(material_feasible=True)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].status == "OPTIMAL"
    assert out["result"].objective_value == 39.0
    result = validate(ds, out["schedule"])
    assert result.valid, [v.message for v in result.violations]
    assert len(result.violations) == 0
