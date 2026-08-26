"""Phase 4.5 Part 2 - production-order material feasibility tests.

Covers the production-order layer on top of ``MaterialFeasibility``: an order
is resolved to (product, quantity) and delegated to
``Dataset.material_feasibility``. Read-only; no inventory consumption,
reservation, or allocation.
"""

import pytest

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    Dataset,
    Material,
    MaterialFeasibility,
    MaterialInventory,
    Order,
    Product,
)


def _dataset() -> Dataset:
    ds = Dataset()
    ds.products["A"] = Product(id="A", name="Product A")
    ds.materials["M_MDF"] = Material(id="M_MDF", name="MDF board")
    ds.materials["M_HINGE"] = Material(id="M_HINGE", name="Hinge")
    ds.materials["M_EDGE"] = Material(id="M_EDGE", name="Edge tape")
    ds.boms["A"] = BOM(product_id="A", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=2.0),
        BomItem(material_id="M_HINGE", quantity_per_unit=4.0),
    ])
    ds.inventory["M_MDF"] = MaterialInventory(material_id="M_MDF", on_hand=200.0)
    ds.inventory["M_HINGE"] = MaterialInventory(material_id="M_HINGE", on_hand=30.0)
    ds.orders["ORD1"] = Order(id="ORD1", product_id="A", quantity=5,
                              release_time=480, due_time=1440)
    return ds


# ------------------------------------------------------------- feasible demand
def test_feasible_demand():
    ds = _dataset()
    result = ds.order_material_feasibility("ORD1")
    assert isinstance(result, MaterialFeasibility)
    assert result.feasible is True
    # A x5: M_MDF 10, M_HINGE 20 - both within stock
    assert result.requirements == {"M_MDF": 10.0, "M_HINGE": 20.0}
    assert result.shortages == {}


# ------------------------------------------------------------------ shortage
def test_demand_with_shortage():
    ds = _dataset()
    ds.orders["ORD2"] = Order(id="ORD2", product_id="A", quantity=10,
                              release_time=480, due_time=1440)
    result = ds.order_material_feasibility("ORD2")
    assert result.feasible is False
    # A x10: M_MDF 20 (ok), M_HINGE 40 vs 30 -> short 10
    assert result.shortages == {"M_HINGE": 10.0}


# ---------------------------------------------------------- multiple materials
def test_multiple_materials_reported():
    ds = _dataset()
    ds.boms["A"] = BOM(product_id="A", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=2.0),
        BomItem(material_id="M_HINGE", quantity_per_unit=4.0),
        BomItem(material_id="M_EDGE", quantity_per_unit=3.0),
    ])
    ds.inventory["M_EDGE"] = MaterialInventory(material_id="M_EDGE", on_hand=50.0)
    result = ds.order_material_feasibility("ORD1")
    assert set(result.requirements) == {"M_MDF", "M_HINGE", "M_EDGE"}
    assert set(result.availability) == {"M_MDF", "M_HINGE", "M_EDGE"}
    assert result.feasible is True


# ----------------------------------------------------------------- zero qty
def test_zero_quantity_demand_is_feasible():
    ds = _dataset()
    ds.orders["ORD0"] = Order(id="ORD0", product_id="A", quantity=0,
                              release_time=480, due_time=1440)
    result = ds.order_material_feasibility("ORD0")
    assert result.feasible is True
    assert result.requirements == {}
    assert result.shortages == {}


# --------------------------------------------------------------- invalid qty
def test_invalid_negative_quantity_raises():
    ds = _dataset()
    ds.orders["ORDN"] = Order(id="ORDN", product_id="A", quantity=-3,
                              release_time=480, due_time=1440)
    with pytest.raises(ValueError):
        ds.order_material_feasibility("ORDN")


def test_unknown_order_raises_key_error():
    ds = _dataset()
    with pytest.raises(KeyError):
        ds.order_material_feasibility("ORD_UNKNOWN")


# -------------------------------------------------------------- deterministic
def test_order_feasibility_is_deterministic():
    ds = generate_dataset(seed=SEED)
    oid = next(iter(ds.orders))
    a = ds.order_material_feasibility(oid)
    b = ds.order_material_feasibility(oid)
    assert a.feasible == b.feasible
    assert a.requirements == b.requirements
    assert a.availability == b.availability
    assert a.shortages == b.shortages
