"""Phase 4.7 Part 1 - material demand interface tests.

Covers ``Dataset.material_demand(order_id)`` and
``Dataset.material_demands()``: the per-order aggregated material demand
view that Phase 5 (APS Solver) will consume. Reuses the existing
``material_requirements`` logic; no BOM or inventory calculation is
duplicated, and no inventory is consumed, reserved, or allocated.
"""

import pytest

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    Dataset,
    Material,
    MaterialInventory,
    Order,
    Product,
)


def _dataset() -> Dataset:
    ds = Dataset()
    ds.products["A"] = Product(id="A", name="Product A")
    ds.products["B"] = Product(id="B", name="Product B")
    ds.products["C"] = Product(id="C", name="Product C")
    ds.materials["M_MDF"] = Material(id="M_MDF", name="MDF board")
    ds.materials["M_HINGE"] = Material(id="M_HINGE", name="Hinge")
    ds.materials["M_EDGE"] = Material(id="M_EDGE", name="Edge tape")
    ds.materials["M_GLUE"] = Material(id="M_GLUE", name="Glue")
    # M_HINGE appears twice in A's BOM to exercise within-order aggregation.
    ds.boms["A"] = BOM(product_id="A", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=2.0),
        BomItem(material_id="M_HINGE", quantity_per_unit=3.0),
        BomItem(material_id="M_HINGE", quantity_per_unit=1.0),
    ])
    ds.boms["B"] = BOM(product_id="B", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=1.0),
        BomItem(material_id="M_EDGE", quantity_per_unit=3.0),
    ])
    ds.orders["O1"] = Order(id="O1", product_id="A", quantity=5, release_time=0, due_time=480)
    ds.orders["O2"] = Order(id="O2", product_id="B", quantity=10, release_time=0, due_time=480)
    ds.inventory["M_MDF"] = MaterialInventory(material_id="M_MDF", on_hand=200.0)
    ds.inventory["M_HINGE"] = MaterialInventory(material_id="M_HINGE", on_hand=30.0)
    ds.inventory["M_EDGE"] = MaterialInventory(material_id="M_EDGE", on_hand=50.0)
    return ds


# ----------------------------------------------------------------- single order
def test_single_order_demand():
    ds = _dataset()
    assert ds.material_demand("O1") == {"M_MDF": 10.0, "M_HINGE": 20.0}


# ------------------------------------------------------------- shared materials
def test_shared_materials_aggregate_within_order():
    ds = _dataset()
    # M_HINGE 3.0 + 1.0 per unit x 5 = 20.0 aggregated within the order.
    demand = ds.material_demand("O1")
    assert demand["M_HINGE"] == 20.0


# ------------------------------------------------------------ multiple orders
def test_multiple_orders_are_isolated():
    ds = _dataset()
    demands = ds.material_demands()
    assert demands["O1"] == {"M_MDF": 10.0, "M_HINGE": 20.0}
    assert demands["O2"] == {"M_MDF": 10.0, "M_EDGE": 30.0}


def test_shared_material_totals_per_order_not_cross_order():
    ds = _dataset()
    demands = ds.material_demands()
    # M_MDF is shared by both orders but each order keeps its own amount.
    assert demands["O1"]["M_MDF"] == 10.0
    assert demands["O2"]["M_MDF"] == 10.0


# ----------------------------------------------------------------- edge cases
def test_zero_quantity_returns_empty_demand():
    ds = _dataset()
    ds.orders["O3"] = Order(id="O3", product_id="B", quantity=0, release_time=0, due_time=480)
    assert ds.material_demand("O3") == {}


def test_negative_quantity_raises_value_error():
    ds = _dataset()
    ds.orders["O3"] = Order(id="O3", product_id="A", quantity=-5, release_time=0, due_time=480)
    with pytest.raises(ValueError):
        ds.material_demand("O3")


def test_unknown_order_raises_key_error():
    ds = _dataset()
    with pytest.raises(KeyError):
        ds.material_demand("O_MISSING")


def test_demand_reuses_material_requirements():
    ds = _dataset()
    assert ds.material_demand("O1") == ds.material_requirements("A", 5)


# ------------------------------------------------------------ deterministic
def test_demand_is_deterministic():
    ds = generate_dataset(seed=SEED)
    for _ in range(3):
        assert ds.material_demands() == ds.material_demands()
    assert ds.material_demands() == {
        oid: ds.material_requirements(order.product_id, order.quantity)
        for oid, order in ds.orders.items()
    }
