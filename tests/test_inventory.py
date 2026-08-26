"""Phase 4.2 inventory domain tests.

Covers the on-hand quantity model (MaterialInventory), its integration with
Dataset, and the deterministic generator inventory data. No consumption,
reservation, or material constraints are involved yet.
"""

from aps_engine.generator import SEED, generate_dataset
from aps_engine.models import Dataset, Material, MaterialInventory


# ------------------------------------------------------- MaterialInventory
def test_inventory_defaults_on_hand_to_zero():
    inv = MaterialInventory(material_id="M_BOARD")
    assert inv.material_id == "M_BOARD"
    assert inv.on_hand == 0.0


def test_inventory_records_on_hand():
    inv = MaterialInventory(material_id="M_BOARD", on_hand=120)
    assert inv.on_hand == 120


# ------------------------------------------------------------------- Dataset
def test_dataset_defaults_have_no_inventory():
    ds = Dataset()
    assert ds.inventory == {}


def test_dataset_inventory_is_keyed_by_material_id():
    ds = Dataset()
    ds.materials["M_BOARD"] = Material(id="M_BOARD", name="Particle board")
    ds.inventory["M_BOARD"] = MaterialInventory(material_id="M_BOARD", on_hand=120)
    assert ds.inventory["M_BOARD"].on_hand == 120


def test_inventory_of_returns_none_when_absent():
    ds = Dataset()
    assert ds.inventory_of("M_UNKNOWN") is None


def test_inventory_of_returns_record_when_present():
    ds = Dataset()
    ds.inventory["M_BOARD"] = MaterialInventory(material_id="M_BOARD", on_hand=120)
    assert ds.inventory_of("M_BOARD").on_hand == 120


# ----------------------------------------------------------------- generator
def test_generator_creates_materials_and_inventory():
    ds = generate_dataset(seed=SEED)
    assert ds.meta["n_materials"] == len(ds.materials) >= 4
    assert ds.meta["n_inventory"] == len(ds.inventory) >= 4
    assert set(ds.inventory) == set(ds.materials), "every material has a record"


def test_generator_inventory_references_existing_materials():
    ds = generate_dataset(seed=SEED)
    for mid, inv in ds.inventory.items():
        assert mid in ds.materials, f"inventory references unknown material {mid}"
        assert inv.material_id == mid
        assert inv.on_hand > 0, f"material {mid} must start with positive stock"


def test_generator_inventory_is_deterministic():
    a = generate_dataset(seed=SEED)
    b = generate_dataset(seed=SEED)
    assert list(a.inventory) == list(b.inventory)
    for mid, inv in a.inventory.items():
        assert inv.on_hand == b.inventory[mid].on_hand


def test_generator_has_limited_stock_material():
    """At least one material is deliberately scarce for future solver tests."""
    ds = generate_dataset(seed=SEED)
    on_hands = [inv.on_hand for inv in ds.inventory.values()]
    assert min(on_hands) < max(on_hands), "stock levels must not be uniform"
    limited = [inv for inv in ds.inventory.values()
               if inv.on_hand == min(on_hands)]
    assert len(limited) == 1, "exactly one material carries the scarce stock"
    assert limited[0].material_id == "M_HINGE"
    assert ds.materials["M_HINGE"].name == "Hinge"


def test_inventory_sits_alongside_existing_domain():
    """Materials + inventory coexist with products/orders without disturbing
    the existing object graph."""
    ds = generate_dataset(seed=SEED)
    assert len(ds.orders) == 10
    assert len(ds.operations) > 0
    for mid, inv in ds.inventory.items():
        assert ds.materials[mid].unit, "material must define a unit"
