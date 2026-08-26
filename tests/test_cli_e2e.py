"""CLI end-to-end subprocess tests (Phase 4 Part 3).

Run the real entry point (`python -m aps_engine`) and assert exit codes,
status, schedule presence and diagnostic output. No manual verification.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "aps_engine", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_cli_valid_exits_zero_with_schedule():
    # The default dataset is material-infeasible (Phase 5 P1), so the valid
    # run uses the material-feasible variant; scheduling output is unchanged.
    proc = _run("--material-feasible")
    assert proc.returncode == 0
    out = proc.stdout
    assert "STATUS: OPTIMAL" in out
    assert "OBJECTIVE (weighted tardiness):" in out
    # schedule is present and printed
    assert "[5] OPERATIONS" in out
    assert "O0001" in out
    assert "E_CUT_A" in out
    # validation succeeds
    assert "valid: True" in out
    assert "Employee violations: 0" in out
    # setup / changeover aggregate is reported
    assert "setup/changeover:" in out
    assert "PHASE 5 COMPLETE" in out


def test_cli_infeasible_exits_one_with_diagnostics():
    proc = _run("--infeasible")
    assert proc.returncode == 1
    out = proc.stdout
    assert "STATUS: INFEASIBLE" in out
    assert "Feasibility Diagnostics:" in out
    # diagnostic code, entity context and message are shown
    assert "EMPLOYEE_SHORTAGE" in out
    assert "Operation: O0001" in out
    assert "Order: ORD000" in out
    assert "Reason:" in out
