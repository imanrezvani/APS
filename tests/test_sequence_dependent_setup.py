"""Phase 6 sequence-dependent setup tests.

Stage 4.1 covers the domain semantics: ``Operation.setup_family_id``,
``Dataset.setup_matrix`` and the shared ``changeover`` helper. Stage 4.2 adds
solver-level tests for the uniform pairwise disjunctive model. Validator and
generator tests are added in later stages.
"""

from aps_engine.models import (
    CalendarDay,
    Dataset,
    DowntimeWindow,
    MaintenanceWindow,
    Machine,
    Operation,
    Order,
    Routing,
    Shift,
    WorkCenter,
    changeover,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


def _op(op_id, setup_time=0, family=""):
    return Operation(id=op_id, order_id="ORD1", sequence=0, work_center_id="WC1",
                     processing_time=60, setup_time=setup_time,
                     setup_family_id=family, allowed_machine_ids=["M1"])


def _ds(matrix=None):
    ds = Dataset()
    if matrix is not None:
        ds.setup_matrix = dict(matrix)
    return ds


# ------------------------------------------------------------------ defaults
def test_operation_setup_family_id_defaults_to_empty():
    op = _op("O1")
    assert op.setup_family_id == ""


def test_dataset_setup_matrix_defaults_to_empty():
    assert Dataset().setup_matrix == {}


# --------------------------------------------------- operation -> operation
def test_changeover_falls_back_to_following_setup_without_matrix():
    ds = _ds()
    a = _op("A", setup_time=5, family="PANEL")
    b = _op("B", setup_time=15, family="FLAT")
    assert changeover(ds, a, b) == 15
    assert changeover(ds, b, a) == 5


def test_changeover_zero_when_setup_zero_and_no_matrix():
    ds = _ds()
    assert changeover(ds, _op("A"), _op("B")) == 0


def test_changeover_same_family_uses_matrix_diagonal():
    ds = _ds({("PANEL", "PANEL"): 10})
    a = _op("A", setup_time=15, family="PANEL")
    b = _op("B", setup_time=15, family="PANEL")
    assert changeover(ds, a, b) == 10


def test_changeover_cross_family_a_to_b():
    ds = _ds({("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20})
    a = _op("A", setup_time=15, family="PANEL")
    b = _op("B", setup_time=15, family="FLAT")
    assert changeover(ds, a, b) == 30


def test_changeover_cross_family_b_to_a_is_directional():
    ds = _ds({("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20})
    a = _op("A", setup_time=15, family="PANEL")
    b = _op("B", setup_time=15, family="FLAT")
    assert changeover(ds, b, a) == 20


def test_changeover_zero_setup_matrix_entry():
    ds = _ds({("PANEL", "FLAT"): 0})
    a = _op("A", setup_time=15, family="PANEL")
    b = _op("B", setup_time=15, family="FLAT")
    assert changeover(ds, a, b) == 0


def test_changeover_missing_matrix_entry_falls_back_to_following_setup():
    ds = _ds({("PANEL", "PANEL"): 10})
    a = _op("A", setup_time=7, family="PANEL")
    b = _op("B", setup_time=13, family="FLAT")
    assert changeover(ds, a, b) == 13


def test_changeover_empty_family_falls_back_to_following_setup():
    ds = _ds({("PANEL", "FLAT"): 30})
    a = _op("A", setup_time=9, family="PANEL")
    b = _op("B", setup_time=11, family="")
    assert changeover(ds, a, b) == 11


# ---------------------------------------------------------------- windows
def test_changeover_to_window_is_zero():
    ds = _ds()
    op = _op("A", setup_time=15)
    w = MaintenanceWindow("M1", 540, 600)
    assert changeover(ds, op, w) == 0
    assert changeover(ds, w, w) == 0


def test_changeover_from_maintenance_is_following_setup():
    ds = _ds()
    op = _op("A", setup_time=15)
    w = MaintenanceWindow("M1", 540, 600)
    assert changeover(ds, w, op) == 15


def test_changeover_from_downtime_is_following_setup():
    ds = _ds()
    op = _op("A", setup_time=15)
    w = DowntimeWindow("M1", 540, 600)
    assert changeover(ds, w, op) == 15


# ------------------------------------------------------------------ solver
def _solver_ds(proc_setups, matrix=None, release=480, due=None, maintenance=()):
    """Single order, sequential ops on one machine, with setup families.

    proc_setups: list of (processing_time, setup_time, family) in routing
    order. The precedence chain fixes the op order, and tight due dates make
    the earliest feasible schedule the unique optimum.
    """
    ds = Dataset()
    ds.shifts = {"A": Shift(id="A", name="A", start_minute=480, end_minute=960)}
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.maintenance = list(maintenance)
    if matrix is not None:
        ds.setup_matrix = dict(matrix)
    op_ids = []
    for k, (proc, setup, family) in enumerate(proc_setups):
        op_id = f"OP{k}"
        op_ids.append(op_id)
        ds.operations[op_id] = Operation(
            id=op_id, order_id="ORD0", sequence=k, work_center_id="WC1",
            processing_time=proc, setup_time=setup, setup_family_id=family,
            allowed_machine_ids=["M1"])
    ds.orders["ORD0"] = Order(id="ORD0", product_id="P1", quantity=1,
                              release_time=release,
                              due_time=due if due is not None else release + 10_000,
                              priority=1)
    ds.routings["ORD0"] = Routing(product_id="P1", operations=op_ids)
    ds.meta["horizon_end"] = 14 * 1440
    return ds


def _solve_by_id(ds):
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2,
                                 random_seed=42))
    assert out["result"].feasible, "pairwise model should find a schedule"
    assert out["result"].optimal, "tight due dates should pin the optimum"
    return {o["operation_id"]: o for o in out["schedule"]["operations"]}


def _two_machine_ds(matrix, release=480, due=600):
    """Two machines in one work center. OPA is compatible with both M1 and M2;
    OPB runs only on M1. Independent single-op orders (no precedence)."""
    ds = Dataset()
    ds.shifts = {"A": Shift(id="A", name="A", start_minute=480, end_minute=960)}
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.machines["M2"] = Machine(id="M2", name="M2", work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1",
                                        machine_ids=["M1", "M2"])
    ds.setup_matrix = dict(matrix)
    ds.operations["OPA"] = Operation(id="OPA", order_id="ORDA", sequence=0,
                                     work_center_id="WC1", processing_time=60,
                                     setup_time=15, setup_family_id="PANEL",
                                     allowed_machine_ids=["M1", "M2"])
    ds.operations["OPB"] = Operation(id="OPB", order_id="ORDB", sequence=0,
                                     work_center_id="WC1", processing_time=60,
                                     setup_time=15, setup_family_id="FLAT",
                                     allowed_machine_ids=["M1"])
    ds.orders["ORDA"] = Order(id="ORDA", product_id="PA", quantity=1,
                              release_time=release, due_time=due, priority=1)
    ds.orders["ORDB"] = Order(id="ORDB", product_id="PB", quantity=1,
                              release_time=release, due_time=due, priority=1)
    ds.routings["ORDA"] = Routing(product_id="PA", operations=["OPA"])
    ds.routings["ORDB"] = Routing(product_id="PB", operations=["OPB"])
    ds.meta["horizon_end"] = 14 * 1440
    return ds


def test_solver_matrix_changeover_binds_over_following_setup():
    ds = _solver_ds([(60, 15, "PANEL"), (60, 15, "FLAT")],
                    matrix={("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20},
                    due=630)
    by_id = _solve_by_id(ds)
    assert by_id["OP0"]["start"] == 480
    # matrix (PANEL -> FLAT) = 30 binds, not the following setup_time of 15
    assert by_id["OP1"]["start"] == 570, f"expected 570, got {by_id['OP1']['start']}"


def test_solver_same_family_diagonal_reduces_gap():
    ds = _solver_ds([(60, 15, "PANEL"), (60, 15, "PANEL")],
                    matrix={("PANEL", "PANEL"): 10}, due=610)
    by_id = _solve_by_id(ds)
    # diagonal 10 wins over setup_time 15
    assert by_id["OP1"]["start"] == 550, f"expected 550, got {by_id['OP1']['start']}"


def test_solver_zero_matrix_entry_allows_no_gap():
    ds = _solver_ds([(60, 15, "PANEL"), (60, 15, "FLAT")],
                    matrix={("PANEL", "FLAT"): 0, ("FLAT", "PANEL"): 0},
                    due=600)
    by_id = _solve_by_id(ds)
    assert by_id["OP1"]["start"] == 540, f"expected 540, got {by_id['OP1']['start']}"


def test_solver_maintenance_and_changeover_not_summed():
    ds = _solver_ds([(60, 15, "PANEL"), (60, 15, "FLAT")],
                    matrix={("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20,
                            ("PANEL", "PANEL"): 10, ("FLAT", "FLAT"): 10},
                    due=700,
                    maintenance=[MaintenanceWindow("M1", 540, 600)])
    by_id = _solve_by_id(ds)
    assert by_id["OP0"]["end"] == 540
    # post-maintenance bound: nxt.setup_time -> start >= 600 + 15 = 615
    # op -> op changeover bound: 540 + 30 = 570. Independent, stronger binds.
    assert by_id["OP1"]["start"] == 615, (
        f"expected 615 (stronger bound, NOT 30+15 summed), got {by_id['OP1']['start']}")


# ------------------------------------------- assignment gating (Phase 3 harden)
def test_operation_assigned_elsewhere_not_constrained_by_candidate_pair():
    """OPA is compatible with both M1 and M2; OPB runs only on M1. M1 hosts
    the (OPA, OPB) setup pair whose changeover exceeds the horizon. Because
    OPA is scheduled on M2, the unselected M1 pair must impose no temporal
    constraint on OPA: the problem stays feasible and OPA starts at its
    earliest position, unaffected by the impossible M1 changeover."""
    ds = _two_machine_ds({("PANEL", "FLAT"): 100_000, ("FLAT", "PANEL"): 100_000,
                          ("PANEL", "PANEL"): 100_000, ("FLAT", "FLAT"): 100_000})
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2,
                                 random_seed=42))
    assert out["result"].feasible, (
        "the unselected M1 candidate pair must not make the model infeasible")
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    assert by_id["OPA"]["machine_id"] == "M2"
    assert by_id["OPB"]["machine_id"] == "M1"
    assert by_id["OPA"]["start"] == 480
    assert by_id["OPB"]["start"] == 480


def test_assigned_pair_changeover_still_binds():
    """Gating must not weaken setup constraints: when both operations ARE on
    the same machine the changeover still binds exactly as before."""
    ds = _two_machine_ds({("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20},
                         due=600)
    # pin OPA onto M1 by removing its alternative machine, so both ops must
    # share M1 and the (OPA, OPB) changeover has to be enforced.
    ds.operations["OPA"].allowed_machine_ids = ["M1"]
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2,
                                 random_seed=42))
    assert out["result"].feasible
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    assert by_id["OPA"]["machine_id"] == "M1"
    assert by_id["OPB"]["machine_id"] == "M1"
    a, b = by_id["OPA"], by_id["OPB"]
    first, second = (a, b) if a["start"] <= b["start"] else (b, a)
    gap = second["start"] - first["end"]
    expected = 30 if first["operation_id"] == "OPA" else 20
    assert gap == expected, f"expected changeover gap {expected}, got {gap}"


# ------------------------------------------- validator (Phase 6 P4 gap A)
def _matrix_validator_ds(matrix, fam_a="PANEL", fam_b="FLAT"):
    """Two same-machine ops with setup families, 24/7, no employees.

    The ops share routing order ORD1 -> [OP0, OP1]; only the setup gap can
    be violated, so SETUP_VIOLATION is the sole possible validator hit.
    """
    ds = Dataset()
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.setup_matrix = dict(matrix)
    ds.operations["OP0"] = _op("OP0", setup_time=15, family=fam_a)
    ds.operations["OP1"] = _op("OP1", setup_time=15, family=fam_b)
    ds.orders["ORD1"] = Order(id="ORD1", product_id="P1", quantity=1,
                              release_time=0, due_time=100_000, priority=1)
    ds.routings["ORD1"] = Routing(product_id="P1", operations=["OP0", "OP1"])
    ds.meta["horizon_end"] = 100_000
    return ds


def _consecutive_schedule(gap):
    """OP0 at [0, 60), OP1 at [60 + gap, 120 + gap) on M1."""
    return {
        "operations": [
            {"operation_id": "OP0", "order_id": "ORD1", "machine_id": "M1",
             "employee_id": None, "start": 0, "end": 60},
            {"operation_id": "OP1", "order_id": "ORD1", "machine_id": "M1",
             "employee_id": None, "start": 60 + gap, "end": 120 + gap},
        ],
        "orders": [
            {"order_id": "ORD1", "completion_time": 120 + gap,
             "due_time": 100_000, "tardiness": 0},
        ],
    }


def test_validator_accepts_matrix_diagonal_below_setup_time():
    # diagonal 10 < setup_time 15: the matrix value governs, not setup_time
    ds = _matrix_validator_ds({("PANEL", "PANEL"): 10},
                              fam_a="PANEL", fam_b="PANEL")
    vr = validate(ds, _consecutive_schedule(gap=10))
    assert vr.valid, [v.code for v in vr.violations]


def test_validator_accepts_zero_matrix_entry():
    ds = _matrix_validator_ds({("PANEL", "FLAT"): 0, ("FLAT", "PANEL"): 0})
    vr = validate(ds, _consecutive_schedule(gap=0))
    assert vr.valid, [v.code for v in vr.violations]


def test_validator_rejects_undersized_matrix_gap():
    # matrix (PANEL -> FLAT) = 30 > setup_time 15: a 20-minute gap is legal by
    # setup_time but violates the matrix changeover
    ds = _matrix_validator_ds({("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20})
    vr = validate(ds, _consecutive_schedule(gap=20))
    assert not vr.valid
    assert any(v.code == "SETUP_VIOLATION" for v in vr.violations)


def test_validator_accepts_full_matrix_gap():
    ds = _matrix_validator_ds({("PANEL", "FLAT"): 30, ("FLAT", "PANEL"): 20})
    vr = validate(ds, _consecutive_schedule(gap=30))
    assert vr.valid, [v.code for v in vr.violations]


def test_solver_matrix_schedules_validate():
    """Solver-valid matrix schedules (diagonal / zero below setup_time) now
    pass the independent validator end-to-end."""
    for proc, matrix, due in [
        ([(60, 15, "PANEL"), (60, 15, "PANEL")],
         {("PANEL", "PANEL"): 10}, 610),
        ([(60, 15, "PANEL"), (60, 15, "FLAT")],
         {("PANEL", "FLAT"): 0, ("FLAT", "PANEL"): 0}, 600),
    ]:
        ds = _solver_ds(proc, matrix=matrix, due=due)
        out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2,
                                     random_seed=42))
        assert out["result"].feasible
        assert out["result"].optimal
        vr = validate(ds, out["schedule"])
        assert vr.valid, [v.code for v in vr.violations]
