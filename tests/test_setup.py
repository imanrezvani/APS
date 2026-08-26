"""Phase 5 setup / changeover tests.

The machine setup feature is backward compatible: ``setup_time`` defaults to
0 and the solver / validator / generator only add setup behaviour when it is
non-zero.

Solver tests use a single order with two operations on one machine so the
precedence chain forces the ordering, and tight due dates make the earliest
feasible schedule the unique optimum.
"""

from aps_engine.generator import SETUP_TIMES, SEED, generate_dataset
from aps_engine.models import (
    CalendarDay,
    Dataset,
    MaintenanceWindow,
    Machine,
    Operation,
    Order,
    Routing,
    Shift,
    WorkCenter,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


# ---------------------------------------------------------------- Part 1: model
def test_operation_setup_time_defaults_to_zero():
    op = Operation(id="O1", order_id="ORD1", sequence=0, work_center_id="WC1",
                   processing_time=60)
    assert op.setup_time == 0


def test_generator_assigns_setup_times():
    ds = generate_dataset(seed=SEED)
    assert ds.meta["n_setup"] == len(ds.operations), "every generated op has a setup"
    for op in ds.operations.values():
        assert op.setup_time > 0
        assert op.setup_time == SETUP_TIMES[op.required_skill_id]
    assert max(op.setup_time for op in ds.operations.values()) <= 20


# ---------------------------------------------------------------- fixtures
def _one_order_ds(proc_setups, release=480, due=None, maintenance=()):
    """Single order, sequential operations on one machine (precedence chain).

    proc_setups: list of (processing_time, setup_time) in routing order.
    """
    ds = Dataset()
    ds.shifts = {"A": Shift(id="A", name="A", start_minute=480, end_minute=960)}
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]
    ds.machines["M1"] = Machine(id="M1", name="M1", work_center_id="WC1")
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1", machine_ids=["M1"])
    ds.maintenance = list(maintenance)
    op_ids = []
    for k, (proc, setup) in enumerate(proc_setups):
        op_id = f"OP{k}"
        op_ids.append(op_id)
        ds.operations[op_id] = Operation(
            id=op_id, order_id="ORD0", sequence=k, work_center_id="WC1",
            processing_time=proc, setup_time=setup, allowed_machine_ids=["M1"])
    ds.orders["ORD0"] = Order(id="ORD0", product_id="P1", quantity=1,
                              release_time=release,
                              due_time=due if due is not None else release + 10_000,
                              priority=1)
    ds.routings["ORD0"] = Routing(product_id="P1", operations=op_ids)
    ds.meta["horizon_end"] = 14 * 1440
    return ds


def _schedule(op_times, completion):
    """op_times: list of (op_id, start, end)."""
    ds_dummy = _one_order_ds([(60, 0)])
    due = ds_dummy.orders["ORD0"].due_time
    return {
        "operations": [
            {"operation_id": op_id, "order_id": "ORD0", "machine_id": "M1",
             "employee_id": None, "start": start, "end": end}
            for op_id, start, end in op_times
        ],
        "orders": [{"order_id": "ORD0", "completion_time": completion,
                    "due_time": due, "tardiness": max(0, completion - due)}],
    }


# ---------------------------------------------------------------- Part 3: validator
def test_validator_flags_insufficient_setup_gap():
    ds = _one_order_ds([(60, 0), (60, 30)])
    schedule = _schedule([("OP0", 480, 540), ("OP1", 540, 600)], completion=600)
    vr = validate(ds, schedule)
    assert any(v.code == "SETUP_VIOLATION" for v in vr.violations)


def test_validator_accepts_sufficient_setup_gap():
    ds = _one_order_ds([(60, 0), (60, 30)])
    schedule = _schedule([("OP0", 480, 540), ("OP1", 570, 630)], completion=630)
    vr = validate(ds, schedule)
    assert vr.valid, [v.message for v in vr.violations]


def test_validator_no_setup_requirement_when_zero():
    ds = _one_order_ds([(60, 0), (60, 0)])
    schedule = _schedule([("OP0", 480, 540), ("OP1", 540, 600)], completion=600)
    vr = validate(ds, schedule)
    assert vr.valid, [v.message for v in vr.violations]


# ---------------------------------------------------------------- Part 2: solver
def test_solver_enforces_setup_gap_between_ops():
    ds = _one_order_ds([(60, 0), (60, 30)], release=480, due=630)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    assert by_id["OP0"]["start"] == 480
    assert by_id["OP1"]["start"] == 570, f"setup 30 must force start 570, got {by_id['OP1']['start']}"


def test_solver_zero_setup_forces_no_gap():
    ds = _one_order_ds([(60, 0), (60, 0)], release=480, due=600)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    assert by_id["OP0"]["start"] == 480
    assert by_id["OP1"]["start"] == 540, f"no setup should allow start 540, got {by_id['OP1']['start']}"


def test_solver_setup_required_after_maintenance():
    ds = _one_order_ds([(60, 0), (60, 30)], release=480, due=690,
                       maintenance=[MaintenanceWindow("M1", 540, 600)])
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
    by_id = {o["operation_id"]: o for o in out["schedule"]["operations"]}
    assert by_id["OP0"]["end"] == 540
    # OP1 must clear the maintenance window (ends 600) AND its setup (30):
    # the extended interval [start - 30, end] cannot overlap [540, 600)
    assert by_id["OP1"]["start"] == 630, f"expected start 630, got {by_id['OP1']['start']}"


def test_default_dataset_with_setup_feasible_and_valid():
    # The default dataset is material-infeasible (Phase 5 P1), so use the
    # material-feasible variant to exercise the setup behavior end to end.
    ds = generate_dataset(seed=SEED, material_feasible=True)
    out = solve(ds, SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42))
    assert out["result"].feasible
    assert out["result"].optimal
    assert validate(ds, out["schedule"]).valid
