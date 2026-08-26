"""Phase 4 Part 2: infeasibility diagnostics.

Bounded layered analysis invoked when CP-SAT returns INFEASIBLE. It does NOT
relax or weaken any constraint and it does NOT prove an exact mathematical
root cause: each layer reports only PROVEN necessary-condition violations.
If every local check passes but the model is still infeasible, the honest
answer is GLOBAL_SCHEDULING_CONFLICT.

Layers (mirror the structure of ``solver/model.py``):

  1. structural pre-solve validation  (validation/pre_solve.py)
  2. machine eligibility              (zero compatible machines)
  3. employee eligibility             (skill, work-center, no staff)
  4. employee availability            (availability windows too short)
  5. calendar / precedence            (op cannot fit any slot, chain too long)
  6. material availability            (aggregate order-book demand > on-hand,
                                      reported as a data-level availability
                                      fact; the solver's material constraint is
                                      time-phased, so this is a strong signal
                                      rather than an exact proof)
  7. fallback                         GLOBAL_SCHEDULING_CONFLICT

Each diagnostic dict carries:
  code, order_id, operation_id, resource_type, resource_id, reason
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from aps_engine.models import Dataset
from aps_engine.validation.pre_solve import ERROR, pre_solve_validate

MACHINE_SHORTAGE = "MACHINE_SHORTAGE"
EMPLOYEE_SHORTAGE = "EMPLOYEE_SHORTAGE"
SKILL_SHORTAGE = "SKILL_SHORTAGE"
WORK_CENTER_SHORTAGE = "WORK_CENTER_SHORTAGE"
EMPLOYEE_AVAILABILITY = "EMPLOYEE_AVAILABILITY"
CALENDAR_CONFLICT = "CALENDAR_CONFLICT"
HORIZON_CONFLICT = "HORIZON_CONFLICT"
PRECEDENCE_CONFLICT = "PRECEDENCE_CONFLICT"
MATERIAL_SHORTAGE = "MATERIAL_SHORTAGE"
GLOBAL_SCHEDULING_CONFLICT = "GLOBAL_SCHEDULING_CONFLICT"

# pre-solve structural codes -> diagnostic category.
# Codes not listed here (UNKNOWN_ORDER, UNKNOWN_OPERATION, DUPLICATE_OPERATION,
# UNKNOWN_EMPLOYEE, INVALID_*) surface with their original code: they are
# precise structural data errors and should not be relabelled.
_STRUCTURAL_MAP = {
    "ZERO_MACHINES": MACHINE_SHORTAGE,
    "UNKNOWN_MACHINE": MACHINE_SHORTAGE,
    "UNKNOWN_WORK_CENTER": WORK_CENTER_SHORTAGE,
    "UNKNOWN_SKILL": SKILL_SHORTAGE,
    "MISSING_REQUIRED_SKILL": SKILL_SHORTAGE,
    "IMPOSSIBLE_AVAILABILITY": EMPLOYEE_AVAILABILITY,
    "UNKNOWN_SHIFT": CALENDAR_CONFLICT,
    "INVALID_SHIFT": CALENDAR_CONFLICT,
    "NO_WORKING_SLOTS": CALENDAR_CONFLICT,
    "RELEASE_BEYOND_HORIZON": HORIZON_CONFLICT,
    "OPERATION_FITS_HORIZON": HORIZON_CONFLICT,
}

DAY_MINUTES = 1440


def _working_slots(ds: Dataset) -> List[Tuple[str, int, int]]:
    """Ordered (shift_id, start_abs, end_abs) slots of the factory calendar."""
    slots: List[Tuple[str, int, int]] = []
    for day in sorted(ds.calendar, key=lambda d: d.day_index):
        if not day.is_working:
            continue
        day_start = day.day_index * DAY_MINUTES
        for sid in day.shift_ids:
            sh = ds.shifts.get(sid)
            if sh is None:
                continue
            slots.append((sid, day_start + sh.start_minute,
                          day_start + sh.end_minute))
    slots.sort(key=lambda s: s[1])
    return slots


def _calendar_fit(ds: Dataset, op) -> Optional[Tuple[str, str, str, str]]:
    """Layer 5 (calendar): op longer than the longest working slot."""
    slots = _working_slots(ds)
    if not slots:
        return None  # no calendar -> 24/7 availability
    longest = max(s1 - s0 for _, s0, s1 in slots)
    if longest < op.processing_time:
        return (CALENDAR_CONFLICT, "calendar", "",
                f"operation {op.id} processing {op.processing_time} > "
                f"longest working slot {longest}")
    return None


def _op_diagnostic(ds: Dataset, op, horizon: int):
    """Most specific PROVEN local violation for one operation, or None.

    Returns (code, resource_type, resource_id, reason).
    """
    valid_machines = [mid for mid in op.allowed_machine_ids if mid in ds.machines]
    if not valid_machines:
        return (MACHINE_SHORTAGE, "machine",
                ",".join(op.allowed_machine_ids) or "<none>",
                f"operation {op.id} has zero compatible machines")

    if not op.employee_required or not op.required_skill_id:
        return _calendar_fit(ds, op)

    if op.required_skill_id not in ds.skills:
        return (SKILL_SHORTAGE, "skill", op.required_skill_id,
                f"operation {op.id} requires undefined skill "
                f"{op.required_skill_id}")

    employees = list(ds.employees.values())
    if not employees:
        return (EMPLOYEE_SHORTAGE, "employee", "",
                f"operation {op.id} requires an employee but none are defined")

    has_skill = [e for e in employees if op.required_skill_id in e.skill_ids]
    if not has_skill:
        return (SKILL_SHORTAGE, "skill", op.required_skill_id,
                f"operation {op.id} requires skill {op.required_skill_id} "
                f"but no employee has it")

    authorized = [e for e in has_skill if op.work_center_id in e.work_center_ids]
    if not authorized:
        return (WORK_CENTER_SHORTAGE, "work_center", op.work_center_id,
                f"operation {op.id} requires work center {op.work_center_id} "
                f"but no skilled employee is authorized for it")

    emp_ids = ",".join(sorted(e.id for e in authorized))
    max_window = max(e.available_until - e.available_from for e in authorized)
    if max_window < op.processing_time:
        return (EMPLOYEE_AVAILABILITY, "employee", emp_ids,
                f"operation {op.id} needs {op.processing_time} minutes but the "
                f"longest employee availability window is {max_window}")

    slots = _working_slots(ds)
    if slots:
        longest = max(s1 - s0 for _, s0, s1 in slots)
        if longest < op.processing_time:
            return (CALENDAR_CONFLICT, "calendar", "",
                    f"operation {op.id} processing {op.processing_time} > "
                    f"longest working slot {longest}")
        usable = any(
            sid in e.shift_ids
            and s1 - s0 >= op.processing_time
            and e.available_from <= s0 and s1 <= e.available_until
            for e in authorized for sid, s0, s1 in slots)
        if not usable:
            window_covers = any(
                s1 - s0 >= op.processing_time
                and e.available_from <= s0 and s1 <= e.available_until
                for e in authorized for _, s0, s1 in slots)
            if not window_covers:
                return (EMPLOYEE_AVAILABILITY, "employee", emp_ids,
                        f"no employee availability window covers a working slot "
                        f"for operation {op.id}")
            return (EMPLOYEE_SHORTAGE, "employee", emp_ids,
                    f"no employee with skill {op.required_skill_id} works a "
                    f"shift that can host operation {op.id}")

    return None


def _material_shortages(ds: Dataset) -> List[Tuple[str, float, float, float]]:
    """Layer 6 (material availability): aggregate order-book demand.

    Returns (material_id, required, available, shortage) for every material
    whose aggregated order-book demand exceeds on-hand inventory. The solver's
    material constraint is time-phased, so this aggregate report is a data
    fact about the order book (more material is demanded than is stocked)
    that flags the materials most likely to drive infeasibility rather than an
    exact mathematical proof. Datasets without BOMs / material demand yield no
    shortages.
    """
    feasibility = ds.order_book_material_feasibility()
    return [(mid,
             float(feasibility.requirements[mid]),
             float(feasibility.availability.get(mid, 0.0)),
             float(feasibility.shortages[mid]))
            for mid in sorted(feasibility.shortages)]


def _precedence_conflicts(ds: Dataset, horizon: int):
    """Layer 5 (precedence): routing chain longer than available working time.

    Necessary condition only: the total processing time of an order's chain
    cannot exceed the factory's working minutes from release to horizon.
    Only reported for multi-operation routings.
    """
    slots = _working_slots(ds)
    for oid, routing in sorted(ds.routings.items()):
        order = ds.orders.get(oid)
        if order is None or len(routing.operations) <= 1:
            continue
        if order.release_time >= horizon:
            continue  # already HORIZON_CONFLICT
        chain = sum(
            ds.operations[op].processing_time
            for op in routing.operations if op in ds.operations)
        if not slots:
            budget = horizon - order.release_time
        else:
            budget = sum(s1 - s0 for _, s0, s1 in slots if s0 >= order.release_time)
        if chain > budget:
            yield oid, chain, budget


def build_diagnostics(ds: Dataset) -> List[Dict]:
    """Produce layered infeasibility diagnostics for an infeasible dataset."""
    horizon = ds.meta.get("horizon_end", 100_000)
    diags: List[Dict] = []
    seen = set()

    def add(code: str, order_id: str = "", operation_id: str = "",
            resource_type: str = "", resource_id: str = "",
            reason: str = "") -> None:
        key = (code, operation_id, resource_id)
        if key in seen:
            return
        seen.add(key)
        diags.append({
            "code": code,
            "order_id": order_id,
            "operation_id": operation_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "reason": reason,
        })

    # Layer 1: structural pre-solve validation
    presolve = pre_solve_validate(ds)
    for issue in presolve.issues:
        if issue.severity != ERROR:
            continue
        if issue.code == "ZERO_QUALIFIED_EMPLOYEES":
            continue  # refined by layers 3-4 per operation
        code = _STRUCTURAL_MAP.get(issue.code, issue.code)
        add(code, issue.order_id, issue.operation_id,
            issue.resource_type, issue.resource_id, issue.message)

    # Layers 2-5: per-operation local eligibility + calendar
    for op_id, op in sorted(ds.operations.items()):
        diag = _op_diagnostic(ds, op, horizon)
        if diag:
            code, rtype, rid, reason = diag
            add(code, op.order_id, op_id, rtype, rid, reason)

    # Layer 5: precedence chain feasibility
    for oid, chain, budget in _precedence_conflicts(ds, horizon):
        add(PRECEDENCE_CONFLICT, order_id=oid, resource_type="operation",
            resource_id=oid,
            reason=f"routing chain of order {oid} needs {chain} minutes but "
                   f"only {budget} working minutes are available from release")

    # Layer 6: aggregate material availability
    for mid, required, available, shortage in _material_shortages(ds):
        add(MATERIAL_SHORTAGE, resource_type="material", resource_id=mid,
            reason=f"order-book demand for {mid} requires {required} units but "
                   f"only {available} are on-hand (short {shortage})")

    # Layer 7: no local root cause proven
    if not diags:
        add(GLOBAL_SCHEDULING_CONFLICT, resource_type="schedule",
            resource_id="",
            reason="all local eligibility checks pass but CP-SAT found no "
                   "feasible schedule (global scheduling conflict)")

    return diags
