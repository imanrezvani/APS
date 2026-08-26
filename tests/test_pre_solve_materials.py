"""Pre-solve material/BOM/inventory integrity tests (Phase 4.6 Part 2).

Each test builds a minimal valid dataset (scheduling entities plus materials,
BOMs and inventory) and breaks one structural invariant, asserting the
expected issue code.
"""

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    CalendarDay,
    Dataset,
    Employee,
    Machine,
    Material,
    MaterialInventory,
    Operation,
    Order,
    Product,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)
from aps_engine.validation.pre_solve import (
    ERROR,
    WARNING,
    pre_solve_validate,
)


def _base_ds():
    """Tiny valid dataset: scheduling entities + product/material/BOM/inventory."""
    ds = Dataset()
    ds.products["P1"] = Product(id="P1", name="P1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.skills["SK1"] = Skill(id="SK1", name="SK1")
    ds.shifts["A"] = Shift(id="A", name="A", start_minute=480, end_minute=960)
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]
    ds.employees["E1"] = Employee(
        id="E1", name="E1", shift_ids=["A"], skill_ids=["SK1"],
        work_center_ids=["WC1"], available_from=0, available_until=1440)
    ds.orders["ORD1"] = Order(id="ORD1", product_id="P1", quantity=1,
                              release_time=480, due_time=800, priority=1)
    ds.operations["OP1"] = Operation(
        id="OP1", order_id="ORD1", sequence=0, work_center_id="WC1",
        processing_time=60, allowed_machine_ids=["M1"],
        required_skill_id="SK1", employee_required=True)
    ds.routings["ORD1"] = Routing(product_id="P1", operations=["OP1"])
    ds.meta["horizon_end"] = 1440

    ds.materials["M_A"] = Material(id="M_A", name="Material A")
    ds.materials["M_B"] = Material(id="M_B", name="Material B")
    ds.boms["P1"] = BOM(product_id="P1", items=[
        BomItem(material_id="M_A", quantity_per_unit=1.0),
        BomItem(material_id="M_B", quantity_per_unit=2.0),
    ])
    ds.inventory["M_A"] = MaterialInventory(material_id="M_A", on_hand=10.0)
    ds.inventory["M_B"] = MaterialInventory(material_id="M_B", on_hand=20.0)
    return ds


def _codes(result):
    return [i.code for i in result.issues]


# ------------------------------------------------------------------- valid
def test_valid_dataset_with_materials_passes():
    ds = _base_ds()
    result = pre_solve_validate(ds)
    assert result.valid
    assert result.issues == []


def test_generated_dataset_passes_with_zero_false_positives():
    result = pre_solve_validate(generate_dataset())
    assert result.valid, [i.message for i in result.issues]
    assert result.issues == []


# ------------------------------------------------------- unknown BOM product
def test_unknown_bom_product_detected():
    ds = _base_ds()
    ds.boms["P1"].product_id = "P_UNKNOWN"
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_PRODUCT" in _codes(result)


# ------------------------------------------------------ unknown BOM material
def test_unknown_bom_material_detected():
    ds = _base_ds()
    ds.boms["P1"].items.append(BomItem(material_id="M_UNKNOWN", quantity_per_unit=1.0))
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_MATERIAL" in _codes(result)


# ----------------------------------------------------------- duplicate material
def test_duplicate_material_in_bom_warns():
    ds = _base_ds()
    ds.boms["P1"].items.append(BomItem(material_id="M_A", quantity_per_unit=1.0))
    result = pre_solve_validate(ds)
    # a warning only: requirements aggregation sums repeated materials
    assert result.valid
    assert "DUPLICATE_MATERIAL" in _codes(result)
    issue = next(i for i in result.issues if i.code == "DUPLICATE_MATERIAL")
    assert issue.severity == WARNING


def test_duplicate_material_definition_detected():
    ds = _base_ds()
    # a second key whose material carries a conflicting id -> not unique
    ds.materials["M_X"] = Material(id="M_A", name="Conflicting A")
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_MATERIAL" in _codes(result)


# --------------------------------------------------------- unknown inventory
def test_unknown_inventory_material_detected():
    ds = _base_ds()
    ds.inventory["M_A"].material_id = "M_UNKNOWN"
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_MATERIAL" in _codes(result)


# ------------------------------------------------------ invalid inventory qty
def test_negative_inventory_quantity_detected():
    ds = _base_ds()
    ds.inventory["M_A"].on_hand = -1.0
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "INVALID_INVENTORY" in _codes(result)


def test_zero_inventory_quantity_is_valid():
    ds = _base_ds()
    ds.inventory["M_A"].on_hand = 0.0
    result = pre_solve_validate(ds)
    assert result.valid


def test_missing_material_inventory_record_is_valid():
    ds = _base_ds()
    del ds.inventory["M_B"]
    result = pre_solve_validate(ds)
    assert result.valid
