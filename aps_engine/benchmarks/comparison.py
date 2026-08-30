"""Phase 6 P2 benchmark harness: solve() vs greedy_solve().

A minimal, deterministic comparison harness that runs the CP-SAT solver
(``solve``) and the greedy reference scheduler (``greedy_solve``) on the same
:class:`~aps_engine.models.Dataset` and reports, for each solver:

  - status
  - objective
  - runtime (wall time, seconds)
  - operations scheduled
  - validity (independent validator result)

Both solvers are run on the exact same Dataset instance and the harness
asserts that neither mutates it. Every reported field is deterministic except
the measured runtimes. No solver, model, validator, CLI, or material semantics
are touched, and the harness only uses the existing deterministic datasets
(``generate_dataset`` and ``generate_infeasible_dataset``).
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from aps_engine.generator import generate_dataset, generate_infeasible_dataset
from aps_engine.models import Dataset
from aps_engine.solver import SolverParams, greedy_solve, solve
from aps_engine.validation.validator import validate

SOLVER_NAMES = ("cp-sat", "greedy")


def run_solver(ds: Dataset, name: str, out: Dict) -> Dict:
    """One report row for a solver run.

    ``out`` is the ``{"result", "schedule"}`` dict returned by either solver.
    Validity is recomputed independently with the validator; an absent
    schedule (infeasible run) is reported as invalid with a NO_SCHEDULE
    violation.
    """
    result = out["result"]
    schedule = out["schedule"]
    validation = validate(ds, schedule)
    return {
        "solver": name,
        "status": result.status,
        "feasible": result.feasible,
        "objective": result.objective_value,
        "runtime_s": round(result.wall_time, 6),
        "operations_scheduled": len(schedule["operations"]) if schedule is not None else 0,
        "valid": validation.valid,
        "n_violations": len(validation.violations),
        "violation_codes": sorted({v.code for v in validation.violations}),
    }


def _compare_rows(cp: Dict, greedy: Dict) -> Dict:
    return {
        "feasibility_agreement": cp["feasible"] == greedy["feasible"],
        "objective_delta": (cp["objective"] - greedy["objective"])
        if (cp["objective"] is not None and greedy["objective"] is not None) else None,
        "runtime_speedup_greedy_vs_cpsat": (cp["runtime_s"] / greedy["runtime_s"])
        if greedy["runtime_s"] > 0 else None,
    }


def compare(ds: Dataset, params: Optional[SolverParams] = None) -> Dict:
    """Compare both solvers on a single dataset.

    Runs ``solve`` then ``greedy_solve`` on the same Dataset instance and
    asserts that neither mutated it. Returns a deterministic report dict (only
    the ``runtime_s`` fields vary between identical runs).
    """
    snapshot = copy.deepcopy(ds)
    cp_out = solve(ds, params)
    greedy_out = greedy_solve(ds)
    assert ds == snapshot, "a solver run mutated the dataset"
    runs = {
        "cp-sat": run_solver(ds, "cp-sat", cp_out),
        "greedy": run_solver(ds, "greedy", greedy_out),
    }
    return {
        "dataset": {
            "seed": ds.meta.get("seed"),
            "material_feasible": ds.meta.get("material_feasible"),
            "n_orders": len(ds.orders),
            "n_operations": len(ds.operations),
        },
        "runs": runs,
        "comparison": _compare_rows(runs["cp-sat"], runs["greedy"]),
    }


def format_report(report: Dict) -> str:
    """Human-readable rendering of a :func:`compare` report (deterministic)."""
    ds = report["dataset"]
    lines = [
        f"dataset: seed={ds['seed']} material_feasible={ds['material_feasible']} "
        f"orders={ds['n_orders']} operations={ds['n_operations']}",
        f"{'solver':<7} {'status':<10} {'objective':>10} {'runtime(s)':>11} "
        f"{'ops':>4} {'valid':>6} {'violations':>10}",
    ]
    for row in report["runs"].values():
        obj = "n/a" if row["objective"] is None else f"{row['objective']:.1f}"
        lines.append(
            f"{row['solver']:<7} {row['status']:<10} {obj:>10} {row['runtime_s']:>11.4f} "
            f"{row['operations_scheduled']:>4} {str(row['valid']):>6} {row['n_violations']:>10}")
    cmp = report["comparison"]
    speedup = "n/a" if cmp["runtime_speedup_greedy_vs_cpsat"] is None \
        else f"{cmp['runtime_speedup_greedy_vs_cpsat']:.5g}x"
    lines.append(
        f"comparison: feasibility_agreement={cmp['feasibility_agreement']} "
        f"objective_delta={cmp['objective_delta']} "
        f"speedup_greedy_vs_cp_sat={speedup}")
    return "\n".join(lines)


def main() -> None:
    """Run the comparison on the deterministic datasets and print reports."""
    datasets: List[tuple] = [
        ("default (material-short)", generate_dataset()),
        ("material-feasible", generate_dataset(material_feasible=True)),
        ("infeasible-by-design", generate_infeasible_dataset()),
    ]
    for name, ds in datasets:
        print(f"== {name} ==")
        print(format_report(compare(ds)))
        print()
