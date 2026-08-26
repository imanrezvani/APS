"""Phase 4.5 Part 1 - material feasibility result tests.

Covers the read-only MaterialFeasibility result composed from
``material_requirements`` and ``material_availability``: feasible flag,
requirements, availability, and shortages. No inventory consumption,
reservation, or allocation is involved.
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


# ------------------------------------------------------------ structure
def test_result_is_a_material_feasibility():
    ds = _dataset()
    result = ds.material_feasibility("A", 5)
    assert isinstance(result, MaterialFeasibility)
    assert result.feasible is True
    assert result.requirements == {"M_MDF": 10.0, "M_HINGE": 20.0}
    assert result.availability == {"M_MDF": 200.0, "M_HINGE": 30.0}
    assert result.shortages == {}


# ----------------------------------------------------------- fully feasible
def test_fully_feasible_material_set():
    ds = _dataset()
    result = ds.material_feasibility("A", 5)
    assert result.feasible is True
    assert result.shortages == {}


# ---------------------------------------------------------------- shortage
def test_one_shortage():
    ds = _dataset()
    # A x10: M_MDF 20 (ok), M_HINGE 40 vs 30 -> short 10
    result = ds.material_feasibility("A", 10)
    assert result.feasible is False
    assert result.shortages == {"M_HINGE": 10.0}
    assert result.availability["M_HINGE"] == 30.0


def test_multiple_shortages():
    ds = _dataset()
    # A x200: M_MDF 400 vs 200 (short 200), M_HINGE 800 vs 30 (short 770)
    result = ds.material_feasibility("A", 200)
    assert result.feasible is False
    assert result.shortages == {"M_MDF": 200.0, "M_HINGE": 770.0}


# ---------------------------------------------------------- exact inventory
def test_exact_inventory_match():
    ds = _dataset()
    # M_MDF 2.0/unit x 100 = 200 == on-hand
    result = ds.material_feasibility("A", 100)
    assert result.availability["M_MDF"] == result.requirements["M_MDF"] == 200.0
    assert "M_MDF" not in result.shortages
    assert result.shortages == {"M_HINGE": 370.0}


# ---------------------------------------------------------- missing inventory
def test_missing_inventory_record_is_zero_stock():
    ds = _dataset()
    del ds.inventory["M_EDGE"]
    result = ds.material_feasibility("B", 10)
    assert result.feasible is False
    assert result.availability["M_EDGE"] == 0.0
    assert result.shortages["M_EDGE"] == 30.0


# ---------------------------------------------------------------- edge cases
def test_zero_quantity_is_feasible_with_empty_result():
    ds = _dataset()
    result = ds.material_feasibility("A", 0)
    assert result.feasible is True
    assert result.requirements == {}
    assert result.availability == {}
    assert result.shortages == {}


def test_negative_quantity_raises():
    ds = _dataset()
    with pytest.raises(ValueError):
        ds.material_feasibility("A", -5)


def test_unknown_product_is_feasible_with_empty_result():
    ds = _dataset()
    result = ds.material_feasibility("P_UNKNOWN", 5)
    assert result.feasible is True
    assert result.requirements == {}
    assert result.shortages == {}


# ---------------------------------------------------------------- deterministic
def test_result_is_deterministic():
    ds = generate_dataset(seed=SEED)
    for _ in range(3):
        a = ds.material_feasibility("P_CABINET", 10)
        b = ds.material_feasibility("P_CABINET", 10)
        assert a.feasible == b.feasible
        assert a.requirements == b.requirements
        assert a.availability == b.availability
        assert a.shortages == b.shortages
