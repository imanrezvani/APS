"""Phase 4.1 material + BOM domain tests.

These tests cover ONLY the new domain models (Material, BomItem, BOM) and
their integration with Dataset. No solver, inventory, or material constraints
are involved yet.
"""

from aps_engine.models import (
    BOM,
    BomItem,
    Dataset,
    Material,
    Order,
    Product,
    Routing,
)


# ------------------------------------------------------------------ Material
def test_material_defaults_unit_to_unit():
    m = Material(id="M1", name="Particle board")
    assert m.id == "M1"
    assert m.name == "Particle board"
    assert m.unit == "unit"


def test_material_custom_unit():
    m = Material(id="M2", name="Edge tape", unit="meter")
    assert m.unit == "meter"


# -------------------------------------------------------------------- BomItem
def test_bom_item_defaults_quantity_to_one():
    item = BomItem(material_id="M1")
    assert item.material_id == "M1"
    assert item.quantity_per_unit == 1.0


def test_bom_item_custom_quantity():
    item = BomItem(material_id="M1", quantity_per_unit=2.5)
    assert item.quantity_per_unit == 2.5


# ----------------------------------------------------------------------- BOM
def test_bom_holds_items_in_order():
    bom = BOM(product_id="P_CABINET", items=[
        BomItem(material_id="M_BOARD", quantity_per_unit=4.0),
        BomItem(material_id="M_EDGE", quantity_per_unit=12.0),
    ])
    assert bom.product_id == "P_CABINET"
    assert [i.material_id for i in bom.items] == ["M_BOARD", "M_EDGE"]


def test_bom_defaults_to_empty_items():
    bom = BOM(product_id="P_DESK")
    assert bom.items == []


# ------------------------------------------------------------------- Dataset
def test_dataset_defaults_have_no_materials_or_boms():
    ds = Dataset()
    assert ds.materials == {}
    assert ds.boms == {}


def test_dataset_materials_and_boms_are_settable():
    ds = Dataset()
    ds.materials["M_BOARD"] = Material(id="M_BOARD", name="Particle board", unit="sheet")
    ds.boms["P_CABINET"] = BOM(product_id="P_CABINET", items=[
        BomItem(material_id="M_BOARD", quantity_per_unit=4.0),
    ])
    assert ds.materials["M_BOARD"].unit == "sheet"
    assert ds.boms["P_CABINET"].items[0].quantity_per_unit == 4.0


def test_bom_for_returns_none_when_absent():
    ds = Dataset()
    assert ds.bom_for("P_UNKNOWN") is None


def test_bom_for_returns_bom_when_present():
    ds = Dataset()
    ds.boms["P_CABINET"] = BOM(product_id="P_CABINET")
    assert ds.bom_for("P_CABINET").product_id == "P_CABINET"


def test_materials_for_returns_empty_list_when_no_bom():
    ds = Dataset()
    assert ds.materials_for("P_UNKNOWN") == []


def test_materials_for_returns_bom_items():
    ds = Dataset()
    ds.boms["P_DESK"] = BOM(product_id="P_DESK", items=[
        BomItem(material_id="M_BOARD", quantity_per_unit=2.0),
    ])
    assert ds.materials_for("P_DESK") == [
        BomItem(material_id="M_BOARD", quantity_per_unit=2.0),
    ]


# ------------------------------------------------- existing models integration
def test_material_bom_sits_alongside_existing_domain():
    """A dataset with products/orders/routings accepts materials + BOMs
    without disturbing the existing object graph."""
    ds = Dataset()
    ds.products["P_CABINET"] = Product(id="P_CABINET", name="Cabinet")
    ds.orders["ORD000"] = Order(id="ORD000", product_id="P_CABINET",
                                quantity=5, release_time=480, due_time=1440)
    ds.routings["ORD000"] = Routing(product_id="P_CABINET", operations=["O0001"])
    ds.materials["M_BOARD"] = Material(id="M_BOARD", name="Particle board")
    ds.boms["P_CABINET"] = BOM(product_id="P_CABINET", items=[
        BomItem(material_id="M_BOARD", quantity_per_unit=4.0),
    ])

    order = ds.orders["ORD000"]
    bom = ds.bom_for(order.product_id)
    assert bom is not None
    assert [i.material_id for i in bom.items] == ["M_BOARD"]
    assert ds.materials["M_BOARD"].name == "Particle board"
    assert ds.materials_for("P_CABINET")[0].quantity_per_unit == 4.0
