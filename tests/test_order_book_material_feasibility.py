"""Phase 4.6 Part 1 - order-book material feasibility tests.

Covers the read-only aggregate of material feasibility across the entire
production order book: requirements summed over all orders, compared with
current inventory, with shortages and a feasible flag. No inventory
consumption, reservation, or allocation.
"""

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
    ds.products["B"] = Product(id="B", name="Product B")
    ds.materials["M_MDF"] = Material(id="M_MDF", name="MDF board")
    ds.materials["M_HINGE"] = Material(id="M_HINGE", name="Hinge")
    ds.materials["M_EDGE"] = Material(id="M_EDGE", name="Edge tape")
    ds.boms["A"] = BOM(product_id="A", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=2.0),
        BomItem(material_id="M_HINGE", quantity_per_unit=4.0),
    ])
    ds.boms["B"] = BOM(product_id="B", items=[
        BomItem(material_id="M_MDF", quantity_per_unit=1.0),
        BomItem(material_id="M_EDGE", quantity_per_unit=3.0),
    ])
    ds.inventory["M_MDF"] = MaterialInventory(material_id="M_MDF", on_hand=200.0)
    ds.inventory["M_HINGE"] = MaterialInventory(material_id="M_HINGE", on_hand=30.0)
    ds.inventory["M_EDGE"] = MaterialInventory(material_id="M_EDGE", on_hand=50.0)
    return ds


def _add_order(ds: Dataset, oid: str, product_id: str, quantity: int) -> None:
    ds.orders[oid] = Order(id=oid, product_id=product_id, quantity=quantity,
                           release_time=480, due_time=1440)


# --------------------------------------------------------- fully feasible
def test_fully_feasible_order_book():
    ds = _dataset()
    # A x5: M_MDF 10, M_HINGE 20 - within stock
    _add_order(ds, "ORD1", "A", 5)
    result = ds.order_book_material_feasibility()
    assert isinstance(result, MaterialFeasibility)
    assert result.feasible is True
    assert result.requirements == {"M_MDF": 10.0, "M_HINGE": 20.0}
    assert result.shortages == {}


# ---------------------------------------------------------------- shortage
def test_one_shortage():
    ds = _dataset()
    # A x10: M_MDF 20 (ok), M_HINGE 40 vs 30 -> short 10
    _add_order(ds, "ORD1", "A", 10)
    result = ds.order_book_material_feasibility()
    assert result.feasible is False
    assert result.shortages == {"M_HINGE": 10.0}


def test_multiple_shortages():
    ds = _dataset()
    # A x200: M_MDF 400 vs 200 (short 200), M_HINGE 800 vs 30 (short 770)
    _add_order(ds, "ORD1", "A", 200)
    result = ds.order_book_material_feasibility()
    assert result.feasible is False
    assert result.shortages == {"M_MDF": 200.0, "M_HINGE": 770.0}


# ------------------------------------------------- shared materials across orders
def test_shared_materials_aggregate_across_orders():
    ds = _dataset()
    # both A and B use M_MDF: A x10 -> 20, B x20 -> 20, total 40
    _add_order(ds, "ORD1", "A", 10)
    _add_order(ds, "ORD2", "B", 20)
    result = ds.order_book_material_feasibility()
    assert result.requirements["M_MDF"] == 40.0
    assert result.requirements["M_HINGE"] == 40.0
    assert result.requirements["M_EDGE"] == 60.0
    assert result.feasible is False
    assert result.shortages == {"M_HINGE": 10.0, "M_EDGE": 10.0}


# ----------------------------------------------------------- missing inventory
def test_missing_inventory_record_is_zero_stock():
    ds = _dataset()
    del ds.inventory["M_EDGE"]
    _add_order(ds, "ORD1", "B", 10)
    result = ds.order_book_material_feasibility()
    assert result.feasible is False
    assert result.availability["M_EDGE"] == 0.0
    assert result.shortages["M_EDGE"] == 30.0


# -------------------------------------------------------------- empty / zero
def test_empty_order_book_is_feasible():
    ds = _dataset()
    result = ds.order_book_material_feasibility()
    assert result.feasible is True
    assert result.requirements == {}
    assert result.availability == {}
    assert result.shortages == {}


def test_zero_quantity_orders_are_feasible():
    ds = _dataset()
    _add_order(ds, "ORD1", "A", 0)
    _add_order(ds, "ORD2", "B", 0)
    result = ds.order_book_material_feasibility()
    assert result.feasible is True
    assert result.requirements == {}
    assert result.shortages == {}


# ---------------------------------------------------------------- deterministic
def test_order_book_feasibility_is_deterministic():
    ds = generate_dataset(seed=SEED)
    a = ds.order_book_material_feasibility()
    b = ds.order_book_material_feasibility()
    assert a.feasible == b.feasible
    assert a.requirements == b.requirements
    assert a.availability == b.availability
    assert a.shortages == b.shortages
