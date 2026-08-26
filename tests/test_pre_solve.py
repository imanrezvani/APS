"""Pre-solve validation tests (Phase 4).

Each test builds a minimal dataset from a shared valid base and breaks one
structural invariant, asserting the expected issue code.
"""

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    CalendarDay,
    Dataset,
    Employee,
    Machine,
    Operation,
    Order,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)
from aps_engine.validation.pre_solve import (
    ERROR,
    PreSolveValidationResult,
    pre_solve_validate,
)


def _base_ds():
    """Tiny valid dataset: 1 order, 1 op, 1 machine, 1 skill, 1 employee."""
    ds = Dataset()
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
    return ds


def _codes(result):
    return [i.code for i in result.issues]


def test_valid_dataset_passes():
    ds = _base_ds()
    result = pre_solve_validate(ds)
    assert isinstance(result, PreSolveValidationResult)
    assert result.valid
    assert result.issues == []


def test_generated_dataset_is_valid():
    result = pre_solve_validate(generate_dataset())
    assert result.valid, [i.message for i in result.issues]


def test_unknown_machine_detected():
    ds = _base_ds()
    ds.operations["OP1"].allowed_machine_ids = ["M1", "M2"]  # M2 undefined
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_MACHINE" in _codes(result)


def test_zero_compatible_machines_detected():
    ds = _base_ds()
    ds.operations["OP1"].allowed_machine_ids = []
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "ZERO_MACHINES" in _codes(result)


def test_unknown_skill_detected():
    ds = _base_ds()
    ds.operations["OP1"].required_skill_id = "NOPE"
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_SKILL" in _codes(result)


def test_zero_qualified_employees_detected():
    ds = _base_ds()
    ds.employees["E1"].skill_ids = []  # E1 no longer has required skill
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "ZERO_QUALIFIED_EMPLOYEES" in _codes(result)


def test_zero_qualified_when_no_employees_defined():
    ds = _base_ds()
    ds.employees.clear()
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "ZERO_QUALIFIED_EMPLOYEES" in _codes(result)


def test_unknown_employee_detected():
    ds = _base_ds()
    ds.employees["E1"].id = "E_X"  # dict key E1 refers to a different id
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_EMPLOYEE" in _codes(result)


def test_invalid_work_center_detected():
    ds = _base_ds()
    ds.operations["OP1"].work_center_id = "WC2"
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_WORK_CENTER" in _codes(result)


def test_duplicate_operation_detected():
    ds = _base_ds()
    ds.orders["ORD2"] = Order(id="ORD2", product_id="P1", quantity=1,
                              release_time=480, due_time=800, priority=1)
    ds.routings["ORD2"] = Routing(product_id="P1", operations=["OP1"])
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "DUPLICATE_OPERATION" in _codes(result)


def test_unknown_operation_detected():
    ds = _base_ds()
    ds.routings["ORD1"].operations = ["OP1", "OP999"]
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_OPERATION" in _codes(result)


def test_missing_order_detected():
    ds = _base_ds()
    ds.operations["OP1"].order_id = "ORD9"
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "UNKNOWN_ORDER" in _codes(result)


def test_impossible_horizon_detected():
    ds = _base_ds()
    ds.orders["ORD1"].release_time = 2000  # >= horizon_end 1440
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "RELEASE_BEYOND_HORIZON" in _codes(result)


def test_operation_cannot_fit_horizon_detected():
    ds = _base_ds()
    ds.operations["OP1"].processing_time = 2000  # > horizon_end 1440
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "OPERATION_FITS_HORIZON" in _codes(result)


def test_missing_required_skill_detected():
    ds = _base_ds()
    ds.operations["OP1"].required_skill_id = ""
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "MISSING_REQUIRED_SKILL" in _codes(result)


def test_impossible_availability_detected():
    ds = _base_ds()
    ds.employees["E1"].available_from = 1000
    ds.employees["E1"].available_until = 500
    result = pre_solve_validate(ds)
    assert not result.valid
    assert "IMPOSSIBLE_AVAILABILITY" in _codes(result)


def test_warning_does_not_invalidate():
    ds = _base_ds()
    ds.orders["ORD2"] = Order(id="ORD2", product_id="P1", quantity=1,
                              release_time=480, due_time=800, priority=1)
    # ORD2 has no routing -> MISSING_ROUTING warning only
    result = pre_solve_validate(ds)
    assert all(i.severity != ERROR for i in result.issues)
    assert result.valid
