"""Phase 6 Part 5: post-solve feasibility root-cause diagnostics tests.

Each scenario builds a minimal dataset that CP-SAT rejects as INFEASIBLE (or
a structurally broken dataset) and asserts that ``analyze_infeasibility``
ranks the expected root cause deterministically. Also covers the CLI
``Root cause:`` output and the feasible no-diagnostic path.
"""

import subprocess
import sys
from pathlib import Path

from aps_engine.generator import generate_dataset
from aps_engine.models import (
    BOM,
    BomItem,
    CalendarDay,
    Dataset,
    Employee,
    Machine,
    MaintenanceWindow,
    Material,
    Operation,
    Order,
    Product,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)
from aps_engine.solver import (
    CALENDAR_LIMITATION,
    CAPACITY_SHORTAGE,
    EMPLOYEE_SHORTAGE,
    MAINTENANCE_DOWNTIME,
    MATERIAL_SHORTAGE,
    MACHINE_CAPACITY,
    SETUP_CHANGEOVER_BURDEN,
    STRUCTURAL_INVALIDITY,
    UNKNOWN_INFEASIBILITY,
    analyze_infeasibility,
)
from aps_engine.solver.diagnostics import (
    CALENDAR_CONFLICT,
    GLOBAL_SCHEDULING_CONFLICT,
)
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve

ROOT = Path(__file__).resolve().parents[1]


def _make_ds(shifts, days, machine_ids, ops, release, horizon=1440,
             skill_id="SK1", employees=()):
    """Minimal dataset (mirrors the Phase 4 diagnostics test fixture)."""
    ds = Dataset()
    ds.shifts = {sid: Shift(id=sid, name=sid, start_minute=s, end_minute=e)
                 for sid, s, e in shifts}
    ds.calendar = [CalendarDay(day_index=d, is_working=shift_ids is not None,
                               shift_ids=shift_ids or [])
                   for d, shift_ids in days]
    ds.work_centers["WC1"] = WorkCenter(id="WC1", name="WC1",
                                        machine_ids=list(machine_ids))
    for mid in machine_ids:
        ds.machines[mid] = Machine(id=mid, name=mid, work_center_id="WC1")
    ds.skills[skill_id] = Skill(id=skill_id, name=skill_id)
    for eid, sids, skids, wcids, a_from, a_until in employees:
        ds.employees[eid] = Employee(
            id=eid, name=eid, shift_ids=list(sids), skill_ids=list(skids),
            work_center_ids=list(wcids), available_from=a_from,
            available_until=a_until)
    by_order = {}
    ds.operations = {}
    for k, (oid, opid, proc, emp_required, allowed) in enumerate(ops):
        if allowed is None:
            allowed = list(machine_ids)
        ds.operations[opid] = Operation(
            id=opid, order_id=oid, sequence=k, work_center_id="WC1",
            processing_time=proc, allowed_machine_ids=list(allowed),
            required_skill_id=skill_id if emp_required else "",
            employee_required=emp_required)
        by_order.setdefault(oid, []).append(opid)
    ds.orders = {oid: Order(id=oid, product_id="P1", quantity=1,
                            release_time=release, due_time=release + 10_000,
                            priority=1)
                 for oid in by_order}
    ds.routings = {oid: Routing(product_id="P1", operations=opids)
                   for oid, opids in by_order.items()}
    ds.meta["horizon_end"] = horizon
    return ds


PARAMS = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)


def _make_material_shortage(ds):
    """Give the dataset a material shortage: product P1 needs MAT1 with no stock."""
    ds.products["P1"] = Product(id="P1", name="P1")
    ds.materials["MAT1"] = Material(id="MAT1", name="MAT1")
    ds.boms["P1"] = BOM(product_id="P1",
                        items=[BomItem(material_id="MAT1", quantity_per_unit=2.0)])
    return ds


def _assert_infeasible(out):
    assert not out["result"].feasible
    assert out["result"].status == "INFEASIBLE"


# -------------------------------------------------------------------- API shape
def test_analyze_api_has_required_keys():
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None),
             ("ORD2", "OP2", 400, False, None)],
        release=480)
    analysis = analyze_infeasibility(ds)
    for key in ("status", "root_cause", "confidence", "rank",
                "details", "metrics", "causes", "diagnostics"):
        assert key in analysis
    assert analysis["status"] == "INFEASIBLE"
    assert analysis["root_cause"] == CAPACITY_SHORTAGE
    assert analysis["confidence"] in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(analysis["details"], list) and analysis["details"]
    assert isinstance(analysis["metrics"], dict)
    assert analysis["causes"] and analysis["causes"][0]["category"] == CAPACITY_SHORTAGE


def test_feasible_dataset_no_diagnostic():
    ds = generate_dataset(material_feasible=True)
    analysis = analyze_infeasibility(ds, [])
    assert analysis["status"] == "FEASIBLE"
    assert analysis["root_cause"] is None
    assert analysis["causes"] == []
    assert analysis["diagnostics"] == []


def test_analyze_does_not_mutate_input_diagnostics():
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 70, False, None)],
        release=480)
    diagnostics = [{"code": CALENDAR_CONFLICT, "reason": "op too long"}]
    snapshot = [dict(d) for d in diagnostics]
    analyze_infeasibility(ds, diagnostics)
    assert diagnostics == snapshot


# -------------------------------------------------------------------- categories
def test_material_shortage_root_cause():
    ds = generate_dataset()  # default dataset is material-infeasible
    analysis = analyze_infeasibility(ds)
    assert analysis["status"] == "INFEASIBLE"
    assert analysis["root_cause"] == MATERIAL_SHORTAGE
    assert analysis["confidence"] == "HIGH"


def test_material_shortage_solver_and_analysis_agree():
    ds = _make_material_shortage(_make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, False, None)],
        release=480))
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == MATERIAL_SHORTAGE
    assert "short" in analysis["details"][0]


def test_capacity_shortage_root_cause():
    # two 400-min exclusive ops cannot share one 480-min slot
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None),
             ("ORD2", "OP2", 400, False, None)],
        release=480)
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    assert GLOBAL_SCHEDULING_CONFLICT in [
        d["code"] for d in out["result"].diagnostics]  # P4 layer unchanged
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == CAPACITY_SHORTAGE
    assert analysis["root_cause"] == MACHINE_CAPACITY  # alias
    assert "M1" in analysis["details"][0]


def test_employee_shortage_root_cause():
    # skilled + authorized employee works shift B, calendar only offers A
    ds = _make_ds(
        shifts=[("A", 480, 960), ("B", 960, 1440)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 60, True, None)],
        release=480,
        employees=[("E1", ["B"], ["SK1"], ["WC1"], 0, 1440)])
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == EMPLOYEE_SHORTAGE
    assert analysis["confidence"] == "MEDIUM"


def test_calendar_limitation_root_cause():
    # only working slot is 60 minutes; op needs 70 -> fits no slot
    ds = _make_ds(
        shifts=[("A", 480, 540)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 70, False, None)],
        release=480)
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == CALENDAR_LIMITATION
    assert analysis["confidence"] == "HIGH"


def test_maintenance_downtime_root_cause():
    # op fits the 480-min slot but maintenance leaves only 40-min free windows
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None)],
        release=480)
    ds.maintenance.append(MaintenanceWindow(machine_id="M1", start=500, end=920))
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == MAINTENANCE_DOWNTIME
    assert "maintenance" in analysis["details"][0]


def test_setup_changeover_burden_root_cause():
    # two 200-min ops fit by processing time but need a 300-min changeover
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 200, False, None),
             ("ORD2", "OP2", 200, False, None)],
        release=480)
    ds.operations["OP1"].setup_family_id = "F1"
    ds.operations["OP1"].setup_time = 5
    ds.operations["OP2"].setup_family_id = "F2"
    ds.operations["OP2"].setup_time = 5
    ds.setup_matrix = {("F1", "F2"): 300, ("F2", "F1"): 300,
                       ("F1", "F1"): 5, ("F2", "F2"): 5}
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == SETUP_CHANGEOVER_BURDEN
    assert "changeover" in analysis["details"][0]


def test_structural_invalidity_root_cause():
    # operation has a non-positive processing time (structural data error)
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 0, False, None)],
        release=480)
    analysis = analyze_infeasibility(ds)
    assert analysis["root_cause"] == STRUCTURAL_INVALIDITY
    assert analysis["confidence"] == "HIGH"
    assert "structural" in analysis["details"][0]


def test_unknown_infeasibility_root_cause():
    # both ops individually fit and machines have capacity, but the single
    # qualified employee cannot cover both 400-min ops inside one 480-min slot
    ds = _make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1", "M2"],
        ops=[("ORD1", "OP1", 400, True, ["M1", "M2"]),
             ("ORD2", "OP2", 400, True, ["M1", "M2"])],
        release=480,
        employees=[("E1", ["A"], ["SK1"], ["WC1"], 0, 1440)])
    out = solve(ds, PARAMS)
    _assert_infeasible(out)
    analysis = analyze_infeasibility(ds, out["result"].diagnostics)
    assert analysis["root_cause"] == UNKNOWN_INFEASIBILITY
    assert analysis["confidence"] == "LOW"
    assert "no proven root cause" in analysis["details"][0]


# -------------------------------------------------------------------- ranking
def test_multiple_simultaneous_causes_deterministic_ranking():
    # material shortage (rank 2) AND capacity shortage (rank 4) together
    ds = _make_material_shortage(_make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None),
             ("ORD2", "OP2", 400, False, None)],
        release=480))
    analysis = analyze_infeasibility(ds)
    assert analysis["root_cause"] == MATERIAL_SHORTAGE
    categories = [c["category"] for c in analysis["causes"]]
    assert categories[0] == MATERIAL_SHORTAGE
    assert CAPACITY_SHORTAGE in categories
    ranks = [c["rank"] for c in analysis["causes"]]
    assert ranks == sorted(ranks)
    assert "secondary causes" in analysis["details"][-1]


def test_deterministic_output_across_calls():
    ds = _make_material_shortage(_make_ds(
        shifts=[("A", 480, 960)], days=[(0, ["A"])],
        machine_ids=["M1"],
        ops=[("ORD1", "OP1", 400, False, None),
             ("ORD2", "OP2", 400, False, None)],
        release=480))
    first = analyze_infeasibility(ds)
    second = analyze_infeasibility(ds)
    assert first == second
    assert first["root_cause"] == second["root_cause"]
    assert first["causes"] == second["causes"]
    assert first["details"] == second["details"]


# -------------------------------------------------------------------- CLI
def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "aps_engine", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_cli_infeasible_reports_material_root_cause():
    proc = _run()
    assert proc.returncode == 1
    out = proc.stdout
    assert "STATUS: INFEASIBLE" in out
    assert "Root cause: MATERIAL_SHORTAGE" in out
    assert "Feasibility Diagnostics:" in out  # existing output preserved


def test_cli_infeasible_reports_employee_root_cause():
    proc = _run("--infeasible")
    assert proc.returncode == 1
    out = proc.stdout
    assert "STATUS: INFEASIBLE" in out
    assert "Root cause: EMPLOYEE_SHORTAGE" in out
    assert "EMPLOYEE_SHORTAGE" in out  # existing diagnostics still shown
