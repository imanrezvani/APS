"""APS Engine CLI: generate -> build -> solve -> extract -> validate -> report.

Feasible runs print the schedule, the validation report, and the read-only
order-book material feasibility report, then exit 0. Infeasible runs print the
root cause (Phase 6 P5 root-cause analysis) followed by the layered feasibility
diagnostics and exit 1.
`python -m aps_engine --infeasible` solves a deterministic infeasible
dataset (used by the E2E tests to exercise the diagnostics path) and
`python -m aps_engine --material-feasible` uses the material-feasible
dataset variant (Phase 4.7).
"""

from __future__ import annotations

import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

from aps_engine.generator import generate_dataset, generate_infeasible_dataset
from aps_engine.models import changeover
from aps_engine.solver.diagnostics import analyze_infeasibility
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


def _setup_summary(ds, schedule) -> Tuple[int, int]:
    """Count machine changeovers and total setup minutes in the schedule.

    Uses the shared ``changeover(prev, nxt)`` so sequence-dependent setup
    matrices are reflected; without setup families this is exactly the
    following operation's ``setup_time`` (unchanged behaviour).
    """
    ops_by_machine: Dict[str, List[Tuple[int, int, str]]] = {}
    for o in schedule["operations"]:
        if o["machine_id"]:
            ops_by_machine.setdefault(o["machine_id"], []).append(
                (o["start"], o["end"], o["operation_id"]))
    changeovers = 0
    setup_minutes = 0
    for intervals in ops_by_machine.values():
        intervals.sort(key=lambda x: x[0])
        for a in range(len(intervals) - 1):
            prev = ds.operations[intervals[a][2]]
            nxt = ds.operations[intervals[a + 1][2]]
            value = changeover(ds, prev, nxt)
            if value > 0:
                changeovers += 1
                setup_minutes += value
    return changeovers, setup_minutes


def _print_diagnostics(diagnostics: List[dict]) -> None:
    print("\nFeasibility Diagnostics:")
    for d in diagnostics:
        print(f"\n[{d['code']}]")
        if d.get("operation_id"):
            print(f"Operation: {d['operation_id']}")
        if d.get("order_id"):
            print(f"Order: {d['order_id']}")
        if d.get("resource_id"):
            print(f"Resource: {d['resource_type']} {d['resource_id']}")
        print(f"Reason: {d['reason']}")


def _print_material_report(ds) -> None:
    """Print the read-only order-book material feasibility report (Phase 4.7)."""
    print("\n[8] MATERIAL FEASIBILITY")
    feasibility = ds.order_book_material_feasibility()
    if feasibility.feasible:
        print("    status: FEASIBLE")
        print("    all material demand is covered by current inventory")
        return
    print("    status: INFEASIBLE")
    print(f"    {'material':<12}{'required':>12}{'available':>12}{'shortage':>12}")
    for mid in sorted(feasibility.shortages):
        req = feasibility.requirements[mid]
        avail = feasibility.availability.get(mid, 0.0)
        short = feasibility.shortages[mid]
        print(f"    {mid:<12}{req:>12.1f}{avail:>12.1f}{short:>12.1f}")


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    use_infeasible = "--infeasible" in args
    use_material_feasible = "--material-feasible" in args

    print("=" * 64)
    print("APS ENGINE - PHASE 5 SETUP & CHANGEOVER")
    print("=" * 64)

    if use_infeasible:
        print("\n[1] Generating deterministic INFEASIBLE dataset ...")
        ds = generate_infeasible_dataset()
    elif use_material_feasible:
        print("\n[1] Generating deterministic MATERIAL-FEASIBLE dataset (seed=42) ...")
        ds = generate_dataset(material_feasible=True)
    else:
        print("\n[1] Generating deterministic dataset (seed=42) ...")
        ds = generate_dataset()
    print(f"    orders={len(ds.orders)} operations={len(ds.operations)} "
          f"machines={len(ds.machines)} work_centers={len(ds.work_centers)}")
    print(f"    shifts={len(ds.shifts)} days={ds.meta.get('n_days', 0)} "
          f"holidays={ds.meta.get('n_holidays', 0)}")
    print(f"    maintenance={len(ds.maintenance)} downtime={len(ds.downtime)}")
    print(f"    skills={len(ds.skills)} employees={len(ds.employees)}")

    print("\n[2] Building CP-SAT model ...")
    params = SolverParams(time_limit_seconds=30, num_search_workers=2, random_seed=42)
    out = solve(ds, params)
    result = out["result"]

    print("\n[3] Solving ...")
    print(f"    STATUS: {result.status}")
    print(f"    OBJECTIVE (weighted tardiness): {result.objective_value}")
    print(f"    best bound: {result.best_bound}")
    print(f"    solve time: {result.wall_time:.2f}s")
    print(f"    conflicts: {result.num_conflicts}  branches: {result.num_branches}")

    if not result.feasible:
        print("\nNo feasible solution found. Validation skipped.")
        analysis = analyze_infeasibility(ds, result.diagnostics)
        print(f"\nRoot cause: {analysis['root_cause']}")
        for line in analysis["details"]:
            print(f"    {line}")
        _print_diagnostics(result.diagnostics)
        return 1

    schedule = out["schedule"]

    print("\n[4] ORDERS")
    print(f"    {'order':<10}{'completion':>12}{'due':>12}{'tardiness':>12}{'priority':>10}")
    for r in schedule["orders"]:
        print(f"    {r['order_id']:<10}{r['completion_time']:>12}{r['due_time']:>12}"
              f"{r['tardiness']:>12}{ds.orders[r['order_id']].priority:>10}")

    print("\n[5] OPERATIONS")
    print(f"    {'operation':<10}{'order':<10}{'machine':<10}{'employee':<10}{'start':>8}{'end':>8}")
    for o in schedule["operations"]:
        print(f"    {o['operation_id']:<10}{o['order_id']:<10}{o['machine_id']:<10}"
              f"{o['employee_id']:<10}{o['start']:>8}{o['end']:>8}")

    print("\n[6] EMPLOYEE ASSIGNMENT COUNTS")
    counts = Counter(o["employee_id"] for o in schedule["operations"])
    for eid in sorted(counts):
        emp = ds.employees[eid]
        print(f"    {eid:<10} {emp.name:<16} {counts[eid]:>3} operations")

    print("\n[7] VALIDATION")
    vr = validate(ds, schedule)
    print(f"    valid: {vr.valid}  violations: {len(vr.violations)}")
    codes = Counter(v.code for v in vr.violations)
    print(f"    calendar (HOLIDAY/SHIFT_BOUNDARY): "
          f"{codes.get('HOLIDAY', 0)}/{codes.get('SHIFT_BOUNDARY', 0)}")
    print(f"    maintenance: {codes.get('MAINTENANCE', 0)}  downtime: {codes.get('DOWNTIME', 0)}")
    print(f"    material (MATERIAL_VIOLATION): {codes.get('MATERIAL_VIOLATION', 0)}")
    changeovers, setup_minutes = _setup_summary(ds, schedule)
    print(f"    setup/changeover: {changeovers} changeovers, {setup_minutes} setup minutes")
    emp_codes = (codes.get("EMPLOYEE_MISSING", 0) + codes.get("UNKNOWN_EMPLOYEE", 0)
                 + codes.get("EMPLOYEE_SKILL", 0) + codes.get("EMPLOYEE_WORK_CENTER", 0)
                 + codes.get("EMPLOYEE_SHIFT", 0) + codes.get("EMPLOYEE_AVAILABILITY", 0)
                 + codes.get("EMPLOYEE_OVERLAP", 0))
    print(f"    Employee violations: {emp_codes}")
    for violation in vr.violations[:20]:
        print(f"    [{violation.code}] {violation.entity}: {violation.message}")
    if not vr.valid:
        return 1

    _print_material_report(ds)

    print("\nPHASE 5 COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
