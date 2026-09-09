"""Phase 8 P4 packaging / entry-point tests (extended by Phase 9 P6).

The heavy CLI end-to-end behaviour (``python -m aps_engine`` subprocess,
schedule/validation output, exit codes) is covered by the existing
``test_cli_e2e.py`` / ``test_cli_objective.py`` suites. These focused tests
verify the packaging wiring only: that ``pyproject.toml`` declares the
``aps-engine`` console script against ``aps_engine.cli.main:main``, that
that dotted target resolves to the real ``main`` callable, and that
``main`` returns the int exit status the generated console wrapper feeds to
``sys.exit``.

The Phase 9 P6 regression block additionally exercises the real entry
points in subprocesses (``python -m aps_engine`` and the installed
``aps-engine`` console script) to prove the API layer did not break them.
"""

from importlib import import_module
from pathlib import Path

from aps_engine.cli.main import main

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def test_pyproject_declares_aps_engine_console_script():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'aps-engine = "aps_engine.cli.main:main"' in text


def test_console_script_target_resolves_to_main():
    module_name, _, attribute = "aps_engine.cli.main:main".partition(":")
    assert attribute == "main"
    assert getattr(import_module(module_name), attribute) is main


def test_main_returns_exit_status_integer():
    # Error paths short-circuit before solving and map to exit code 1.
    assert main(["--objective", "bogus"]) == 1
    assert main(["--objective"]) == 1
    # A successful run maps to exit code 0.
    assert main(["--material-feasible"]) == 0


# --------------------------------------------------------------------------- P6
# Phase 9 regression: the CLI and the installed ``aps-engine`` console script
# must remain functional after the API layer was added on top of the engine.

def test_module_cli_entry_unknown_objective_returns_1():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "aps_engine", "--objective", "bogus"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "unknown objective" in result.stderr


def test_console_script_entry_successful_run():
    import shutil
    import subprocess

    executable = shutil.which("aps-engine")
    if executable is None:
        import pytest

        pytest.skip("aps-engine console script not on PATH")
    result = subprocess.run(
        [executable, "--material-feasible"], cwd=ROOT,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0
    assert "VALIDATION" in result.stdout


def test_console_script_entry_unknown_objective_exit_code():
    import shutil
    import subprocess

    executable = shutil.which("aps-engine")
    if executable is None:
        import pytest

        pytest.skip("aps-engine console script not on PATH")
    result = subprocess.run(
        [executable, "--objective", "bogus"], cwd=ROOT,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "unknown objective" in result.stderr
