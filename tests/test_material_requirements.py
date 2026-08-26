"""Phase 4.4 Part 1 - material requirements API tests.

Covers the pure aggregation of BOM quantities for an arbitrary production
quantity: single products, multiple products, shared-material aggregation,
multiplication, and quantity edge cases. No inventory availability,
reservation, or consumption is involved.
"""

import pytest

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    Dataset,
    Material,
    MaterialInventory,
    Product,
)


def _dataset_with_boms() -> Dataset:
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
    return ds


# ------------------------------------------------------- single product
def test_single_product_requirement():
    ds = _dataset_with_boms()
    req = ds.material_requirements("A", 3)
    assert req == {"M_MDF": 6.0, "M_HINGE": 12.0}


# ---------------------------------------------------- BOM multiplication
def test_bom_quantity_multiplication():
    ds = _dataset_with_boms()
    assert ds.material_requirements("B", 2) == {"M_MDF": 2.0, "M_EDGE": 6.0}
    assert ds.material_requirements("A", 1) == {"M_MDF": 2.0, "M_HINGE": 4.0}


# ----------------------------------------------------- multiple products
def test_multiple_products_compute_independently():
    ds = _dataset_with_boms()
    assert ds.material_requirements("A", 2) == {"M_MDF": 4.0, "M_HINGE": 8.0}
    assert ds.material_requirements("B", 2) == {"M_MDF": 2.0, "M_EDGE": 6.0}


# ----------------------------------------- aggregation of shared materials
def test_aggregates_repeated_materials_in_one_bom():
    ds = Dataset()
    ds.products["C"] = Product(id="C", name="Product C")
    ds.materials["M_SCREW"] = Material(id="M_SCREW", name="Screws")
    ds.boms["C"] = BOM(product_id="C", items=[
        BomItem(material_id="M_SCREW", quantity_per_unit=1.0),
        BomItem(material_id="M_SCREW", quantity_per_unit=2.0),
        BomItem(material_id="M_SCREW", quantity_per_unit=0.5),
    ])
    assert ds.material_requirements("C", 4) == {"M_SCREW": 14.0}


def test_shared_material_across_products_aggregates_per_product():
    ds = _dataset_with_boms()
    # both products use M_MDF; each requirement is computed independently
    assert ds.material_requirements("A", 1)["M_MDF"] == 2.0
    assert ds.material_requirements("B", 1)["M_MDF"] == 1.0


# ------------------------------------------------------------ edge cases
def test_zero_quantity_yields_no_requirements():
    ds = _dataset_with_boms()
    assert ds.material_requirements("A", 0) == {}


def test_negative_quantity_raises():
    ds = _dataset_with_boms()
    with pytest.raises(ValueError):
        ds.material_requirements("A", -1)


def test_unknown_product_yields_empty_requirements():
    ds = _dataset_with_boms()
    assert ds.material_requirements("P_UNKNOWN", 5) == {}


def test_product_without_bom_yields_empty_requirements():
    ds = _dataset_with_boms()
    ds.products["N"] = Product(id="N", name="No BOM")
    assert ds.material_requirements("N", 5) == {}


# ---------------------------------------------------------------- deterministic
def test_requirements_are_deterministic():
    ds = generate_dataset(seed=SEED)
    for _ in range(3):
        assert ds.material_requirements("P_CABINET", 10) == \
            ds.material_requirements("P_CABINET", 10)


def test_generator_products_produce_expected_requirements():
    ds = generate_dataset(seed=SEED)
    req = ds.material_requirements("P_SHELF", 2)
    assert req == {"M_BOARD": 1.0}


# ------------------------------------------------------- Part 2: availability
def _dataset_with_inventory() -> Dataset:
    ds = _dataset_with_boms()
    ds.inventory["M_MDF"] = MaterialInventory(material_id="M_MDF", on_hand=200.0)
    ds.inventory["M_HINGE"] = MaterialInventory(material_id="M_HINGE", on_hand=30.0)
    ds.inventory["M_EDGE"] = MaterialInventory(material_id="M_EDGE", on_hand=50.0)
    return ds


def test_all_materials_available():
    ds = _dataset_with_inventory()
    # A x5: M_MDF 10, M_HINGE 20 - both within stock 200 / 30
    shortages = ds.material_availability("A", 5)
    assert shortages == {"M_MDF": 0.0, "M_HINGE": 0.0}


def test_partial_shortage():
    ds = _dataset_with_inventory()
    # A x10: M_MDF needs 20 (stock 200, sufficient), M_HINGE needs 40 (stock 30, short 10)
    shortages = ds.material_availability("A", 10)
    assert shortages["M_MDF"] == 0.0
    assert shortages["M_HINGE"] == 10.0


def test_multiple_shortages():
    ds = _dataset_with_inventory()
    # A x200: M_MDF needs 400 (short 200), M_HINGE needs 800 (short 770)
    a = ds.material_availability("A", 200)
    assert a == {"M_MDF": 200.0, "M_HINGE": 770.0}
    # B x100: M_MDF needs 100 (ok), M_EDGE needs 300 (short 250)
    b = ds.material_availability("B", 100)
    assert b == {"M_MDF": 0.0, "M_EDGE": 250.0}


def test_exact_inventory_match():
    ds = _dataset_with_inventory()
    # M_MDF 2.0/unit, stock 200 -> exactly 100 units
    shortages = ds.material_availability("A", 100)
    assert shortages["M_MDF"] == 0.0
    # M_HINGE 4.0/unit x 7.5 units = 30 == stock
    assert ds.material_availability("A", 7.5)["M_HINGE"] == 0.0


def test_missing_inventory_record_is_full_shortage():
    ds = _dataset_with_inventory()
    # M_EDGE has stock on record, but remove it: treat as zero stock
    del ds.inventory["M_EDGE"]
    shortages = ds.material_availability("B", 10)
    assert shortages["M_EDGE"] == 30.0  # 3.0/unit x 10, no stock


def test_zero_production_quantity_has_no_shortages():
    ds = _dataset_with_inventory()
    assert ds.material_availability("A", 0) == {}


def test_negative_quantity_raises_for_availability():
    ds = _dataset_with_inventory()
    with pytest.raises(ValueError):
        ds.material_availability("A", -5)


def test_unknown_product_has_no_shortages():
    ds = _dataset_with_inventory()
    assert ds.material_availability("P_UNKNOWN", 5) == {}


def test_availability_is_deterministic():
    ds = generate_dataset(seed=SEED)
    for _ in range(3):
        assert ds.material_availability("P_CABINET", 10) == \
            ds.material_availability("P_CABINET", 10)
