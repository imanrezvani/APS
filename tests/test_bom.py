"""Phase 4.3 BOM integration tests.

Covers BOM generation in the deterministic dataset, the Dataset helpers
``bom_for()`` / ``materials_for()``, reference integrity (Product -> BOM ->
Material), positive quantities, and single- vs multi-material BOMs.

BOM is reference data only in this phase: no consumption, inventory,
allocation, or material constraints are involved.
"""

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import BOM, BomItem, Dataset, Material, Product


# ---------------------------------------------------------------- generation
def test_every_product_has_a_bom():
    ds = generate_dataset(seed=SEED)
    assert ds.meta["n_boms"] == len(ds.products) == 5
    for pid in ds.products:
        assert pid in ds.boms, f"product {pid} must have a BOM"
        assert ds.boms[pid].product_id == pid


def test_bom_generation_is_deterministic():
    a = generate_dataset(seed=SEED)
    b = generate_dataset(seed=SEED)
    assert list(a.boms) == list(b.boms)
    for pid, bom in a.boms.items():
        assert [(i.material_id, i.quantity_per_unit) for i in bom.items] == \
            [(i.material_id, i.quantity_per_unit) for i in b.boms[pid].items]


def test_bom_items_meta_count():
    ds = generate_dataset(seed=SEED)
    assert ds.meta["n_bom_items"] == sum(len(b.items) for b in ds.boms.values())
    assert ds.meta["n_bom_items"] >= len(ds.boms)


# ------------------------------------------------------------ helpers on Dataset
def test_bom_for_returns_bom_for_existing_product():
    ds = generate_dataset(seed=SEED)
    bom = ds.bom_for("P_CABINET")
    assert isinstance(bom, BOM)
    assert bom.product_id == "P_CABINET"


def test_materials_for_returns_items():
    ds = generate_dataset(seed=SEED)
    items = ds.materials_for("P_CABINET")
    assert items, "cabinet BOM must have at least one item"
    assert all(isinstance(i, BomItem) for i in items)


# -------------------------------------------------------- reference integrity
def test_bom_references_existing_product():
    ds = generate_dataset(seed=SEED)
    for bom in ds.boms.values():
        assert bom.product_id in ds.products


def test_bom_items_reference_existing_material():
    ds = generate_dataset(seed=SEED)
    for bom in ds.boms.values():
        for item in bom.items:
            assert item.material_id in ds.materials, \
                f"{bom.product_id} references unknown material {item.material_id}"


def test_all_quantities_are_positive():
    ds = generate_dataset(seed=SEED)
    for bom in ds.boms.values():
        for item in bom.items:
            assert item.quantity_per_unit > 0, \
                f"{bom.product_id}:{item.material_id} has non-positive quantity"


# ------------------------------------------------------------- structure types
def test_single_material_bom_exists():
    ds = generate_dataset(seed=SEED)
    single = [pid for pid, bom in ds.boms.items() if len(bom.items) == 1]
    assert single, "at least one single-material BOM is required"
    assert "P_SHELF" in single


def test_multi_material_bom_exists():
    ds = generate_dataset(seed=SEED)
    multi = [pid for pid, bom in ds.boms.items() if len(bom.items) > 1]
    assert multi, "at least one multi-material BOM is required"
    assert len(multi) >= len(ds.boms) - 1


def test_bom_connects_product_to_material():
    """Product -> BOM -> Material: resolve each item back to a real Material."""
    ds = generate_dataset(seed=SEED)
    for bom in ds.boms.values():
        product = ds.products[bom.product_id]
        for item in bom.items:
            material = ds.materials[item.material_id]
            assert material.id == item.material_id
            assert product.id == bom.product_id


# ------------------------------------------------------------------ edge cases
def test_bom_for_unknown_product_returns_none():
    ds = generate_dataset(seed=SEED)
    assert ds.bom_for("P_UNKNOWN") is None


def test_materials_for_unknown_product_returns_empty():
    ds = generate_dataset(seed=SEED)
    assert ds.materials_for("P_UNKNOWN") == []


def test_bom_for_product_without_bom_returns_none():
    ds = Dataset()
    ds.products["P_NEW"] = Product(id="P_NEW", name="New product")
    assert ds.bom_for("P_NEW") is None
    assert ds.materials_for("P_NEW") == []


def test_zero_and_negative_quantities_never_generated():
    ds = generate_dataset(seed=SEED)
    quantities = [i.quantity_per_unit for b in ds.boms.values() for i in b.items]
    assert all(q > 0 for q in quantities)
    assert 0 not in quantities


def test_bom_item_dataclass_allows_any_quantity():
    """The reference-data dataclass does not enforce positivity; that is the
    generator's job (validated in test_all_quantities_are_positive)."""
    zero = BomItem(material_id="M_BOARD", quantity_per_unit=0.0)
    negative = BomItem(material_id="M_BOARD", quantity_per_unit=-1.0)
    assert zero.quantity_per_unit == 0.0
    assert negative.quantity_per_unit == -1.0


def test_manually_built_dataset_with_bom():
    ds = Dataset()
    ds.products["P_X"] = Product(id="P_X", name="X")
    ds.materials["M_A"] = Material(id="M_A", name="A")
    ds.boms["P_X"] = BOM(product_id="P_X", items=[
        BomItem(material_id="M_A", quantity_per_unit=2.0),
    ])
    assert ds.bom_for("P_X").items[0].quantity_per_unit == 2.0
    assert ds.materials_for("P_X")[0].material_id == "M_A"
