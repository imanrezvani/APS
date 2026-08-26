"""CLI material feasibility tests (Phase 4.7 Part 3 + Phase 5 Part 1).

Run the real entry point (`python -m aps_engine`). Since Phase 5 Part 1, the
default (material-short) dataset is INFEASIBLE at the solver: the CLI reports
it through the diagnostics path (MATERIAL_SHORTAGE) and exits 1. The
`--material-feasible` variant reports FEASIBLE in the [8] MATERIAL FEASIBILITY
report and exits 0.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "aps_engine", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120)


# ------------------------------------------------------------- feasible dataset
def test_cli_feasible_dataset_reports_feasible():
    proc = _run("--material-feasible")
    assert proc.returncode == 0
    out = proc.stdout
    assert "[8] MATERIAL FEASIBILITY" in out
    assert "status: FEASIBLE" in out
    assert "all material demand is covered by current inventory" in out
    assert "status: INFEASIBLE" not in out


# ------------------------------------------------------- infeasible/default dataset
def test_cli_default_dataset_is_infeasible_with_material_shortage():
    proc = _run()
    assert proc.returncode == 1
    out = proc.stdout
    assert "STATUS: INFEASIBLE" in out
    assert "Feasibility Diagnostics:" in out
    assert "MATERIAL_SHORTAGE" in out
    assert "Resource: material M_BOARD" in out


# -------------------------------------------------------------- shortage values
def test_cli_reports_shortage_values_in_diagnostics():
    proc = _run()
    assert proc.returncode == 1
    out = proc.stdout
    # M_BOARD: req=389.0, avail=120.0, short=269.0 (default dataset, seed 42).
    assert "M_BOARD" in out
    assert "389.0" in out
    assert "120.0" in out
    assert "269.0" in out


# ------------------------------------------------ existing scheduling output intact
def test_cli_existing_scheduling_output_remains_present():
    proc = _run("--material-feasible")
    out = proc.stdout
    assert proc.returncode == 0
    assert "STATUS: OPTIMAL" in out
    assert "OBJECTIVE (weighted tardiness):" in out
    assert "[4] ORDERS" in out
    assert "[5] OPERATIONS" in out
    assert "[6] EMPLOYEE ASSIGNMENT COUNTS" in out
    assert "[7] VALIDATION" in out
    assert "valid: True" in out
    assert "material (MATERIAL_VIOLATION): 0" in out
    assert "Employee violations: 0" in out
    assert "setup/changeover:" in out
    assert "[8] MATERIAL FEASIBILITY" in out
    assert "status: FEASIBLE" in out
    assert "PHASE 5 COMPLETE" in out


# --------------------------------------------------------------- exit codes
def test_cli_exit_codes():
    # default (material-short) is now infeasible -> 1
    assert _run().returncode == 1
    # material-feasible -> 0, deterministic-infeasible demo -> 1
    assert _run("--material-feasible").returncode == 0
    assert _run("--infeasible").returncode == 1
