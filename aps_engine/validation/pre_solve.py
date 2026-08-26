"""Phase 4 pre-solve structural validation.

Runs BEFORE the CP-SAT solver to detect obvious impossible inputs:
unknown references (machines, skills, work centers, shifts, employees,
orders, operations), zero compatible resources, impossible availability
windows and horizon overflows.

This is NOT a mathematical feasibility proof. If every check passes and
CP-SAT still reports INFEASIBLE, the cause is a global scheduling conflict
that pre-solve intentionally does not classify.

The employee-eligibility check mirrors the solver's static candidate
filter in ``solver/model.py:_employees`` so pre-solve and CP-SAT agree on
candidate construction. Employee shift / availability are only checked
structurally (a usable working slot must exist); the exact slot selection
stays a dynamic solver decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from aps_engine.models import Dataset

ERROR = "error"
WARNING = "warning"

DAY_MINUTES = 1440


@dataclass
class PreSolveIssue:
    code: str
    severity: str  # ERROR or WARNING
    message: str
    order_id: str = ""
    operation_id: str = ""
    resource_type: str = ""  # machine | employee | skill | work_center | shift | order | operation | routing
    resource_id: str = ""


@dataclass
class PreSolveValidationResult:
    valid: bool
    issues: List[PreSolveIssue] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "n_issues": len(self.issues),
            "issues": [i.__dict__ for i in self.issues],
        }


def pre_solve_validate(ds: Dataset) -> PreSolveValidationResult:
    """Run all structural checks against the dataset."""
    issues: List[PreSolveIssue] = []
    _check_orders(ds, issues)
    _check_shifts(ds, issues)
    _check_calendar(ds, issues)
    _check_work_centers(ds, issues)
    _check_machines(ds, issues)
    _check_skills(ds, issues)
    _check_materials(ds, issues)
    _check_boms(ds, issues)
    _check_inventory(ds, issues)
    _check_employees(ds, issues)
    _check_routings(ds, issues)
    _check_operations(ds, issues)
    _check_operations_employee(ds, issues)
    _check_horizon(ds, issues)
    return PreSolveValidationResult(
        valid=all(i.severity != ERROR for i in issues), issues=issues)


# ------------------------------------------------------------------ helpers
def _add(issues: List[PreSolveIssue], code: str, severity: str, message: str,
         order_id: str = "", operation_id: str = "",
         resource_type: str = "", resource_id: str = "") -> None:
    issues.append(PreSolveIssue(
        code=code, severity=severity, message=message, order_id=order_id,
        operation_id=operation_id, resource_type=resource_type,
        resource_id=resource_id))


def _working_slots(ds: Dataset) -> List[Tuple[str, int, int]]:
    """Ordered (shift_id, start_abs, end_abs) slots of the factory calendar.

    Unknown shift references are skipped (reported separately).
    """
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


def _horizon_end(ds: Dataset) -> int:
    return ds.meta.get("horizon_end", 100_000)


# ------------------------------------------------------------------ checks
def _check_orders(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for oid, order in sorted(ds.orders.items()):
        if order.id != oid:
            _add(issues, "UNKNOWN_ORDER", ERROR,
                 f"order dict key {oid!r} does not match order.id {order.id!r}",
                 resource_type="order", resource_id=oid)
        if order.release_time < 0:
            _add(issues, "INVALID_RELEASE_TIME", ERROR,
                 f"release_time {order.release_time} < 0",
                 order_id=oid, resource_type="order", resource_id=oid)
        if order.due_time < order.release_time:
            _add(issues, "INVALID_DUE_TIME", ERROR,
                 f"due_time {order.due_time} < release_time {order.release_time}",
                 order_id=oid, resource_type="order", resource_id=oid)


def _check_shifts(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for sid, shift in sorted(ds.shifts.items()):
        if shift.id != sid:
            _add(issues, "UNKNOWN_SHIFT", ERROR,
                 f"shift dict key {sid!r} does not match shift.id {shift.id!r}",
                 resource_type="shift", resource_id=sid)
        if not (0 <= shift.start_minute < shift.end_minute <= DAY_MINUTES):
            _add(issues, "INVALID_SHIFT", ERROR,
                 f"shift {sid} window [{shift.start_minute},{shift.end_minute}) "
                 f"not inside a single day",
                 resource_type="shift", resource_id=sid)


def _check_calendar(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    if not ds.calendar:
        return  # empty calendar -> backward-compatible 24/7 scheduling
    for day in sorted(ds.calendar, key=lambda d: d.day_index):
        for sid in day.shift_ids:
            if sid not in ds.shifts:
                _add(issues, "UNKNOWN_SHIFT", ERROR,
                     f"working day {day.day_index} references unknown shift {sid!r}",
                     resource_type="shift", resource_id=sid)
    if not _working_slots(ds):
        _add(issues, "NO_WORKING_SLOTS", ERROR,
             "calendar exists but has no working shift slots",
             resource_type="calendar", resource_id="calendar")


def _check_work_centers(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for wcid, wc in sorted(ds.work_centers.items()):
        if wc.id != wcid:
            _add(issues, "UNKNOWN_WORK_CENTER", ERROR,
                 f"work-center dict key {wcid!r} does not match id {wc.id!r}",
                 resource_type="work_center", resource_id=wcid)
        for mid in wc.machine_ids:
            if mid not in ds.machines:
                _add(issues, "UNKNOWN_MACHINE", ERROR,
                     f"work center {wcid} references unknown machine {mid!r}",
                     resource_type="work_center", resource_id=wcid)


def _check_machines(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for mid, machine in sorted(ds.machines.items()):
        if machine.id != mid:
            _add(issues, "UNKNOWN_MACHINE", ERROR,
                 f"machine dict key {mid!r} does not match id {machine.id!r}",
                 resource_type="machine", resource_id=mid)
        if machine.work_center_id not in ds.work_centers:
            _add(issues, "UNKNOWN_WORK_CENTER", ERROR,
                 f"machine {mid} references unknown work center "
                 f"{machine.work_center_id!r}",
                 resource_type="machine", resource_id=mid)


def _check_skills(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for sid, skill in sorted(ds.skills.items()):
        if skill.id != sid:
            _add(issues, "UNKNOWN_SKILL", ERROR,
                 f"skill dict key {sid!r} does not match id {skill.id!r}",
                 resource_type="skill", resource_id=sid)


def _check_materials(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for mid, material in sorted(ds.materials.items()):
        if material.id != mid:
            _add(issues, "UNKNOWN_MATERIAL", ERROR,
                 f"material dict key {mid!r} does not match id {material.id!r}",
                 resource_type="material", resource_id=mid)


def _check_boms(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for pid, bom in sorted(ds.boms.items()):
        if bom.product_id != pid:
            _add(issues, "UNKNOWN_PRODUCT", ERROR,
                 f"BOM dict key {pid!r} does not match product_id {bom.product_id!r}",
                 resource_type="product", resource_id=pid)
        if bom.product_id not in ds.products:
            _add(issues, "UNKNOWN_PRODUCT", ERROR,
                 f"BOM references unknown product {bom.product_id!r}",
                 resource_type="product", resource_id=bom.product_id)
        seen: Dict[str, int] = {}
        for item in bom.items:
            if item.material_id not in ds.materials:
                _add(issues, "UNKNOWN_MATERIAL", ERROR,
                     f"BOM {bom.product_id} references unknown material "
                     f"{item.material_id!r}",
                     resource_type="material", resource_id=item.material_id)
            seen[item.material_id] = seen.get(item.material_id, 0) + 1
        for mid, count in seen.items():
            if count > 1:
                _add(issues, "DUPLICATE_MATERIAL", WARNING,
                     f"BOM {bom.product_id} lists material {mid!r} {count} times "
                     f"(requirements aggregation would sum the quantities)",
                     resource_type="material", resource_id=mid)


def _check_inventory(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for mid, inv in sorted(ds.inventory.items()):
        if inv.material_id != mid:
            _add(issues, "UNKNOWN_MATERIAL", ERROR,
                 f"inventory dict key {mid!r} does not match material_id "
                 f"{inv.material_id!r}",
                 resource_type="material", resource_id=mid)
        if inv.material_id not in ds.materials:
            _add(issues, "UNKNOWN_MATERIAL", ERROR,
                 f"inventory references unknown material {inv.material_id!r}",
                 resource_type="material", resource_id=inv.material_id)
        if inv.on_hand < 0:
            _add(issues, "INVALID_INVENTORY", ERROR,
                 f"inventory for material {mid} has negative on_hand {inv.on_hand}",
                 resource_type="material", resource_id=mid)


def _check_employees(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for eid, emp in sorted(ds.employees.items()):
        if emp.id != eid:
            _add(issues, "UNKNOWN_EMPLOYEE", ERROR,
                 f"employee dict key {eid!r} does not match id {emp.id!r}",
                 resource_type="employee", resource_id=eid)
        if emp.available_from < 0 or emp.available_until < emp.available_from:
            _add(issues, "IMPOSSIBLE_AVAILABILITY", ERROR,
                 f"employee {eid} availability "
                 f"[{emp.available_from},{emp.available_until}) is impossible",
                 resource_type="employee", resource_id=eid)
        for sid in emp.shift_ids:
            if sid not in ds.shifts:
                _add(issues, "UNKNOWN_SHIFT", ERROR,
                     f"employee {eid} references unknown shift {sid!r}",
                     resource_type="employee", resource_id=eid)
        for skill in emp.skill_ids:
            if skill not in ds.skills:
                _add(issues, "UNKNOWN_SKILL", ERROR,
                     f"employee {eid} references unknown skill {skill!r}",
                     resource_type="employee", resource_id=eid)
        for wc in emp.work_center_ids:
            if wc not in ds.work_centers:
                _add(issues, "UNKNOWN_WORK_CENTER", ERROR,
                     f"employee {eid} references unknown work center {wc!r}",
                     resource_type="employee", resource_id=eid)


def _check_routings(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    # global operation ownership: an operation may belong to one routing only
    owner: Dict[str, str] = {}
    for order_id, routing in sorted(ds.routings.items()):
        if order_id not in ds.orders:
            _add(issues, "UNKNOWN_ORDER", ERROR,
                 f"routing references order {order_id!r} not in dataset",
                 order_id=order_id, resource_type="routing", resource_id=order_id)
        seen: Dict[str, int] = {}
        for op_id in routing.operations:
            if op_id not in ds.operations:
                _add(issues, "UNKNOWN_OPERATION", ERROR,
                     f"routing {order_id} references unknown operation {op_id!r}",
                     order_id=order_id, resource_type="routing",
                     resource_id=order_id)
            if op_id in seen:
                _add(issues, "DUPLICATE_OPERATION", ERROR,
                     f"routing {order_id} lists operation {op_id!r} twice",
                     order_id=order_id, operation_id=op_id,
                     resource_type="routing", resource_id=order_id)
            seen[op_id] = seen.get(op_id, 0) + 1
            if op_id in owner and owner[op_id] != order_id:
                _add(issues, "DUPLICATE_OPERATION", ERROR,
                     f"operation {op_id!r} referenced by both "
                     f"{owner[op_id]!r} and {order_id!r}",
                     operation_id=op_id, resource_type="operation",
                     resource_id=op_id)
            owner.setdefault(op_id, order_id)
    for oid in sorted(ds.orders):
        if oid not in ds.routings:
            _add(issues, "MISSING_ROUTING", WARNING,
                 f"order {oid} has no routing",
                 order_id=oid, resource_type="order", resource_id=oid)


def _check_operations(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    routed: set = set()
    for routing in ds.routings.values():
        routed.update(routing.operations)
    for op_id, op in sorted(ds.operations.items()):
        if op.id != op_id:
            _add(issues, "UNKNOWN_OPERATION", ERROR,
                 f"operation dict key {op_id!r} does not match id {op.id!r}",
                 resource_type="operation", resource_id=op_id)
        if op.order_id not in ds.orders:
            _add(issues, "UNKNOWN_ORDER", ERROR,
                 f"operation {op_id} references unknown order {op.order_id!r}",
                 operation_id=op_id, order_id=op.order_id,
                 resource_type="operation", resource_id=op_id)
        if op.processing_time <= 0:
            _add(issues, "INVALID_PROCESSING_TIME", ERROR,
                 f"operation {op_id} processing_time {op.processing_time} <= 0",
                 operation_id=op_id, resource_type="operation", resource_id=op_id)
        if op.work_center_id not in ds.work_centers:
            _add(issues, "UNKNOWN_WORK_CENTER", ERROR,
                 f"operation {op_id} references unknown work center "
                 f"{op.work_center_id!r}",
                 operation_id=op_id, resource_type="work_center",
                 resource_id=op.work_center_id)
        known = [mid for mid in op.allowed_machine_ids if mid in ds.machines]
        for mid in op.allowed_machine_ids:
            if mid not in ds.machines:
                _add(issues, "UNKNOWN_MACHINE", ERROR,
                     f"operation {op_id} references unknown machine {mid!r}",
                     operation_id=op_id, resource_type="machine", resource_id=mid)
        if not known:
            _add(issues, "ZERO_MACHINES", ERROR,
                 f"operation {op_id} has zero compatible machines",
                 operation_id=op_id, resource_type="machine", resource_id=op_id)
        if op.employee_required and not op.required_skill_id:
            _add(issues, "MISSING_REQUIRED_SKILL", ERROR,
                 f"operation {op_id} requires an employee but has no "
                 f"required_skill_id",
                 operation_id=op_id, resource_type="skill", resource_id=op_id)
        elif op.employee_required and op.required_skill_id not in ds.skills:
            _add(issues, "UNKNOWN_SKILL", ERROR,
                 f"operation {op_id} references unknown skill "
                 f"{op.required_skill_id!r}",
                 operation_id=op_id, resource_type="skill",
                 resource_id=op.required_skill_id)
        if op_id not in routed:
            _add(issues, "ORPHAN_OPERATION", WARNING,
                 f"operation {op_id} is not referenced by any routing",
                 operation_id=op_id, resource_type="operation", resource_id=op_id)


def _qualified_employees(ds: Dataset, op) -> List[str]:
    """Employees matching the solver's static eligibility filter.

    Mirrors ``solver/model.py:_employees`` (skill + work-center + duration
    fits availability) and additionally requires at least one working slot
    fully inside the employee's availability window that uses one of the
    employee's shifts, when a calendar is present.
    """
    slots = _working_slots(ds)
    qualified: List[str] = []
    for eid, emp in sorted(ds.employees.items()):
        if op.required_skill_id not in emp.skill_ids:
            continue
        if op.work_center_id not in emp.work_center_ids:
            continue
        if emp.available_until - emp.available_from < op.processing_time:
            continue
        if slots:
            usable = any(
                sid in emp.shift_ids
                and s1 - s0 >= op.processing_time
                and emp.available_from <= s0 and s1 <= emp.available_until
                for sid, s0, s1 in slots)
            if not usable:
                continue
        qualified.append(eid)
    return qualified


def _check_operations_employee(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    for op_id, op in sorted(ds.operations.items()):
        if not op.employee_required or not op.required_skill_id:
            continue
        if op.required_skill_id not in ds.skills:
            continue
        qualified = _qualified_employees(ds, op)
        if not qualified:
            _add(issues, "ZERO_QUALIFIED_EMPLOYEES", ERROR,
                 f"operation {op_id} requires skill {op.required_skill_id} "
                 f"but no employee is qualified",
                 operation_id=op_id, resource_type="employee",
                 resource_id=op.required_skill_id)


def _check_horizon(ds: Dataset, issues: List[PreSolveIssue]) -> None:
    horizon = _horizon_end(ds)
    for oid, order in sorted(ds.orders.items()):
        if order.release_time >= horizon:
            _add(issues, "RELEASE_BEYOND_HORIZON", ERROR,
                 f"order {oid} release_time {order.release_time} >= horizon "
                 f"{horizon}",
                 order_id=oid, resource_type="order", resource_id=oid)
    for op_id, op in sorted(ds.operations.items()):
        if op.processing_time > horizon:
            _add(issues, "OPERATION_FITS_HORIZON", ERROR,
                 f"operation {op_id} processing_time {op.processing_time} > "
                 f"horizon {horizon}",
                 operation_id=op_id, resource_type="operation", resource_id=op_id)
            continue
        order = ds.orders.get(op.order_id)
        if order is not None and order.release_time + op.processing_time > horizon:
            _add(issues, "OPERATION_FITS_HORIZON", ERROR,
                 f"operation {op_id} cannot fit into horizon {horizon}: "
                 f"release {order.release_time} + processing {op.processing_time} "
                 f"exceeds horizon",
                 operation_id=op_id, order_id=op.order_id,
                 resource_type="operation", resource_id=op_id)
