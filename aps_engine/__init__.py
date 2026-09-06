"""APS Engine.

Deterministic production scheduling for a wood/furniture factory built on
OR-Tools CP-SAT: orders, operations, routings, machines, work centers,
shifts/calendar, employees/skills, sequence-dependent setup, and materials/
BOM/inventory feasibility. Ships a CLI (``python -m aps_engine`` or the
``aps-engine`` console script), JSON dataset/result persistence
(``aps_engine.io``) and a thin programmatic service facade (``plan``).
"""

from aps_engine.api import ResultDocument, plan

__version__ = "0.1.0"

__all__ = ["ResultDocument", "plan", "__version__"]
