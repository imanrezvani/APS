"""CLI objective selection tests (Phase 7 P3).

Run the real entry point (`python -m aps_engine`) and assert the selected
objective is threaded through to the report, that the default stays
weighted tardiness, and that invalid objective values fail cleanly.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "aps_engine", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_cli_default_objective_is_weighted_tardiness():
    proc = _run("--material-feasible")
    assert proc.returncode == 0
    assert "OBJECTIVE (weighted tardiness): 39.0" in proc.stdout
    assert "valid: True" in proc.stdout


def test_cli_explicit_weighted_tardiness():
    proc = _run("--material-feasible", "--objective", "weighted_tardiness")
    assert proc.returncode == 0
    assert "OBJECTIVE (weighted tardiness): 39.0" in proc.stdout
    assert "valid: True" in proc.stdout


def test_cli_explicit_makespan():
    proc = _run("--material-feasible", "--objective", "makespan")
    assert proc.returncode == 0
    assert "STATUS: OPTIMAL" in proc.stdout
    assert "OBJECTIVE (makespan): 1350.0" in proc.stdout
    assert "valid: True" in proc.stdout


def test_cli_invalid_objective_fails_cleanly():
    proc = _run("--material-feasible", "--objective", "bogus")
    assert proc.returncode == 1
    assert "ERROR: unknown objective 'bogus'" in proc.stderr
    assert "weighted_tardiness" in proc.stderr
    assert "makespan" in proc.stderr


def test_cli_objective_missing_value_fails_cleanly():
    proc = _run("--material-feasible", "--objective")
    assert proc.returncode == 1
    assert "--objective requires a value" in proc.stderr
