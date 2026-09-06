"""Phase 8 P4 packaging / entry-point tests.

The heavy CLI end-to-end behaviour (``python -m aps_engine`` subprocess,
schedule/validation output, exit codes) is covered by the existing
``test_cli_e2e.py`` / ``test_cli_objective.py`` suites. These focused tests
verify the packaging wiring only: that ``pyproject.toml`` declares the
``aps-engine`` console script against ``aps_engine.cli.main:main``, that
that dotted target resolves to the real ``main`` callable, and that
``main`` returns the int exit status the generated console wrapper feeds to
``sys.exit``.
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
