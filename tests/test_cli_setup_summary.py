"""Phase 6 P4 CLI setup-summary test.

The ``setup/changeover`` summary must reflect the sequence-dependent setup
matrix via the shared ``changeover`` helper, not just the following
operation's ``setup_time``.
"""

from aps_engine.cli.main import _setup_summary
from aps_engine.models import (
    Dataset,
    Machine,
    Operation,
    Order,
    Routing,
    WorkCenter,
)


def _matrix_ds():
    ds = Dataset()
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.setup_matrix = {("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20,
                       ("PANEL", "PANEL"): 5, ("FLAT", "FLAT"): 5}
    for k, family in (("OP0", "PANEL"), ("OP1", "FLAT"), ("OP2", "PANEL")):
        ds.operations[k] = Operation(
            id=k, order_id="ORD0", sequence=int(k[-1]), work_center_id="WC1",
            processing_time=60, setup_time=15, setup_family_id=family,
            allowed_machine_ids=["M1"])
    ds.orders["ORD0"] = Order(id="ORD0", product_id="P1", quantity=1,
                              release_time=0, due_time=100_000, priority=1)
    ds.routings["ORD0"] = Routing(product_id="P1", operations=["OP0", "OP1", "OP2"])
    return ds


def test_setup_summary_uses_matrix_changeover_values():
    ds = _matrix_ds()
    schedule = {
        "operations": [
            {"operation_id": "OP0", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 0, "end": 60},
            {"operation_id": "OP1", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 90, "end": 150},    # PANEL->FLAT = 30
            {"operation_id": "OP2", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 170, "end": 230},   # FLAT->PANEL = 20
        ],
        "orders": [],
    }
    assert _setup_summary(ds, schedule) == (2, 50)


def test_setup_summary_default_no_families_uses_setup_time():
    ds = _matrix_ds()
    ds.setup_matrix = {}
    for op in ds.operations.values():
        op.setup_family_id = ""
    schedule = {
        "operations": [
            {"operation_id": "OP0", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 0, "end": 60},
            {"operation_id": "OP1", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 75, "end": 135},
            {"operation_id": "OP2", "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": 150, "end": 210},
        ],
        "orders": [],
    }
    assert _setup_summary(ds, schedule) == (2, 30)
