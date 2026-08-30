"""Independent Phase 3 schedule validator.

The validator does NOT inspect the CP-SAT model. It receives only
(dataset, schedule) and re-derives every check from first principles:

  - operation precedence
  - machine compatibility
  - machine overlap (capacity)
  - machine setup / changeover (gap >= setup_time of the following operation)
  - release time
  - factory calendar (same-shift containment, no holidays)
  - machine maintenance / downtime avoidance
  - employee assignment (exactly one, skill, work center, shift,
    availability, non-overlap)
  - completion times & tardiness (recomputed, compared with schedule)
  - material consumption (time-phased cumulative working stock derived from
    the schedule and BOMs, compared with on-hand inventory)

Violation codes:
  PRECEDENCE, MACHINE_COMPAT, MACHINE_OVERLAP, SETUP_VIOLATION, RELEASE_TIME,
  HOLIDAY, SHIFT_BOUNDARY, MAINTENANCE, DOWNTIME,
  EMPLOYEE_MISSING, UNKNOWN_EMPLOYEE, EMPLOYEE_SKILL, EMPLOYEE_WORK_CENTER,
  EMPLOYEE_SHIFT, EMPLOYEE_AVAILABILITY, EMPLOYEE_OVERLAP,
  COMPLETION_MISMATCH, TARDINESS_MISMATCH, MACHINE_MISSING, DUPLICATE_OPERATION,
  MATERIAL_VIOLATION
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from aps_engine.models import Dataset, changeover

MATERIAL_VIOLATION = "MATERIAL_VIOLATION"


@dataclass
class Violation:
    code: str
    entity: str  # operation id, order id, or material id
    message: str
    details: Dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    valid: bool
    violations: List[Violation] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "n_violations": len(self.violations),
            "violations": [v.__dict__ for v in self.violations],
        }


def _overlap(a_s: int, a_e: int, b_s: int, b_e: int) -> bool:
    return a_s < b_e and b_s < a_e


def _shift_slot(ds: Dataset, start: int, end: int):
    """Return (code, message) if [start, end) is not inside one working shift."""
    if start < 0 or end <= start:
        return "SHIFT_BOUNDARY", f"invalid interval [{start},{end})"
    s_day, e_day = start // 1440, end // 1440
    if s_day != e_day:
        return "SHIFT_BOUNDARY", f"operation crosses a day boundary: [{start},{end})"
    day = next((d for d in ds.calendar if d.day_index == s_day), None)
    if day is None or not day.is_working:
        return "HOLIDAY", f"operation on non-working day {s_day}: [{start},{end})"
    s_m, e_m = start % 1440, end % 1440
    for sid in day.shift_ids:
        sh = ds.shifts.get(sid)
        if sh is None:
            continue
        if sh.start_minute <= s_m and e_m <= sh.end_minute:
            return None
    return "SHIFT_BOUNDARY", f"operation not contained in a single shift: [{start},{end})"


def _shift_of(ds: Dataset, start: int, end: int):
    """Return the shift id whose slot fully contains [start, end), else None."""
    if start < 0 or end <= start or start // 1440 != end // 1440:
        return None
    day = next((d for d in ds.calendar if d.day_index == start // 1440), None)
    if day is None or not day.is_working:
        return None
    s_m, e_m = start % 1440, end % 1440
    for sid in day.shift_ids:
        sh = ds.shifts.get(sid)
        if sh is None:
            continue
        if sh.start_minute <= s_m and e_m <= sh.end_minute:
            return sid
    return None


def _material_shortages(dataset: Dataset, by_id: Dict[str, Dict]):
    """Independent time-phased material consumption check (Phase 5 Part 3).

    Each order commits its full BOM material demand for the whole duration of
    its production chain (start of its first operation to end of its last
    operation), and the committed working stock of a material at any instant
    is the sum of the demands of all orders whose chain spans that instant.
    This is re-derived purely from the schedule and the BOMs - the CP-SAT
    model is never inspected. Returns a dict mapping each material whose peak
    committed quantity exceeds its on-hand inventory to
    (required, available, shortage), where ``required`` is the peak
    simultaneous committed quantity and ``available`` the on-hand inventory
    (0.0 when no inventory record exists).
    """
    spans = []
    for order_id, routing in dataset.routings.items():
        if not routing.operations:
            continue
        first, last = routing.operations[0], routing.operations[-1]
        if first not in by_id or last not in by_id:
            continue  # missing operation is reported elsewhere
        spans.append((order_id, by_id[first]["start"], by_id[last]["end"]))
    rows: Dict[str, List[tuple]] = {}
    for order_id, start, end in spans:
        for mid, qty in dataset.material_demand(order_id).items():
            if qty <= 0:
                continue
            rows.setdefault(mid, []).append((start, end, qty))
    shortages: Dict[str, Tuple[float, float, float]] = {}
    for mid, intervals in rows.items():
        events = sorted({t for (s, e, _) in intervals for t in (s, e)})
        peak = 0.0
        for t in events:
            peak = max(peak, sum(q for s, e, q in intervals if s <= t < e))
        record = dataset.inventory_of(mid)
        available = record.on_hand if record else 0.0
        if peak > available:
            shortages[mid] = (peak, available, peak - available)
    return shortages


def validate(dataset: Dataset, schedule: Dict) -> ValidationResult:
    v = ValidationResult(valid=True)

    if schedule is None:
        return ValidationResult(valid=False, violations=[
            Violation("NO_SCHEDULE", "-", "no schedule produced")])

    ops = schedule.get("operations", [])
    orders = schedule.get("orders", [])
    by_id: Dict[str, Dict] = {}
    for o in ops:
        if o["operation_id"] in by_id:
            v.violations.append(Violation(
                "DUPLICATE_OPERATION", o["operation_id"],
                f"operation scheduled more than once ({by_id[o['operation_id']]['machine_id']} "
                f"and {o['machine_id']})"))
        by_id[o["operation_id"]] = o

    # coverage: every dataset operation must appear in the schedule
    for op_id in dataset.operations:
        if op_id not in by_id:
            v.violations.append(Violation("MACHINE_MISSING", op_id, "operation not scheduled"))
    for o in ops:
        if o["operation_id"] not in dataset.operations:
            v.violations.append(Violation("UNKNOWN_OPERATION", o["operation_id"],
                                          "operation not present in dataset"))

    for o in ops:
        op = dataset.operations.get(o["operation_id"])
        if op is None:
            continue
        # machine compatibility
        mid = o["machine_id"]
        if mid is None or mid not in op.allowed_machine_ids:
            v.violations.append(Violation(
                "MACHINE_COMPAT", o["operation_id"],
                f"assigned machine {mid} not in allowed {op.allowed_machine_ids}"))
        # release time
        order = dataset.orders[op.order_id]
        if o["start"] < order.release_time:
            v.violations.append(Violation(
                "RELEASE_TIME", o["operation_id"],
                f"start {o['start']} < order release {order.release_time}"))
        # factory calendar: same-shift containment, no holidays
        if dataset.calendar and dataset.shifts and o["machine_id"] is not None:
            hit = _shift_slot(dataset, o["start"], o["end"])
            if hit:
                v.violations.append(Violation(hit[0], o["operation_id"], hit[1]))
        # machine maintenance / downtime avoidance
        if o["machine_id"] is not None:
            for w in dataset.maintenance:
                if w.machine_id == o["machine_id"] and \
                        _overlap(o["start"], o["end"], w.start, w.end):
                    v.violations.append(Violation(
                        "MAINTENANCE", o["operation_id"],
                        f"overlaps maintenance on {w.machine_id} [{w.start},{w.end})"))
            for w in dataset.downtime:
                if w.machine_id == o["machine_id"] and \
                        _overlap(o["start"], o["end"], w.start, w.end):
                    v.violations.append(Violation(
                        "DOWNTIME", o["operation_id"],
                        f"overlaps downtime on {w.machine_id} [{w.start},{w.end})"))
        # employee assignment (Phase 3)
        if op.employee_required:
            eid = o.get("employee_id")
            if eid is None:
                v.violations.append(Violation(
                    "EMPLOYEE_MISSING", o["operation_id"],
                    "operation requires exactly one employee"))
            elif eid not in dataset.employees:
                v.violations.append(Violation(
                    "UNKNOWN_EMPLOYEE", o["operation_id"],
                    f"employee {eid} not in dataset"))
            else:
                emp = dataset.employees[eid]
                if op.required_skill_id not in emp.skill_ids:
                    v.violations.append(Violation(
                        "EMPLOYEE_SKILL", o["operation_id"],
                        f"employee {eid} lacks required skill {op.required_skill_id}"))
                if op.work_center_id not in emp.work_center_ids:
                    v.violations.append(Violation(
                        "EMPLOYEE_WORK_CENTER", o["operation_id"],
                        f"employee {eid} not authorized for work center {op.work_center_id}"))
                if dataset.calendar and dataset.shifts:
                    sid = _shift_of(dataset, o["start"], o["end"])
                    if sid is not None and sid not in emp.shift_ids:
                        v.violations.append(Violation(
                            "EMPLOYEE_SHIFT", o["operation_id"],
                            f"employee {eid} not assigned to shift {sid}"))
                if not (emp.available_from <= o["start"] and o["end"] <= emp.available_until):
                    v.violations.append(Violation(
                        "EMPLOYEE_AVAILABILITY", o["operation_id"],
                        f"[{o['start']},{o['end']}) outside employee {eid} availability "
                        f"[{emp.available_from},{emp.available_until})"))

    # machine overlap
    by_machine: Dict[str, List[tuple]] = {}
    for o in ops:
        if o["machine_id"]:
            by_machine.setdefault(o["machine_id"], []).append((o["start"], o["end"], o["operation_id"]))
    for mid, intervals in by_machine.items():
        intervals.sort(key=lambda x: (x[0], x[1]))
        for a in range(len(intervals)):
            for b in range(a + 1, len(intervals)):
                if intervals[b][0] >= intervals[a][1]:
                    break
                v.violations.append(Violation(
                    "MACHINE_OVERLAP", f"{intervals[a][2]},{intervals[b][2]}",
                    f"overlap on machine {mid}: [{intervals[a][0]},{intervals[a][1]}] and "
                    f"[{intervals[b][0]},{intervals[b][1]}]"))

    # machine setup / changeover: between consecutive operations on the same
    # machine the gap must cover the changeover of that pair (the setup-matrix
    # value when both operations carry a setup_family_id and the dataset
    # defines a setup_matrix, else the setup time of the following operation;
    # ``changeover`` is the shared source of truth with the solver). The
    # window -> operation bound (``op.setup_time``) is unchanged: maintenance
    # / downtime windows are checked separately above.
    for mid, intervals in by_machine.items():
        intervals.sort(key=lambda x: (x[0], x[1]))
        for a in range(len(intervals) - 1):
            prev, nxt = intervals[a], intervals[a + 1]
            prev_op = dataset.operations.get(prev[2])
            nxt_op = dataset.operations.get(nxt[2])
            if prev_op is None or nxt_op is None:
                continue  # unknown operation reported elsewhere
            setup = changeover(dataset, prev_op, nxt_op)
            if nxt[0] < prev[1] + setup:
                v.violations.append(Violation(
                    "SETUP_VIOLATION", f"{prev[2]}->{nxt[2]}",
                    f"on machine {mid}: start({nxt[2]})={nxt[0]} < "
                    f"end({prev[2]})={prev[1]} + setup {setup}"))

    # employee overlap
    by_employee: Dict[str, List[tuple]] = {}
    for o in ops:
        eid = o.get("employee_id")
        if eid:
            by_employee.setdefault(eid, []).append((o["start"], o["end"], o["operation_id"]))
    for eid, intervals in by_employee.items():
        intervals.sort(key=lambda x: (x[0], x[1]))
        for a in range(len(intervals)):
            for b in range(a + 1, len(intervals)):
                if intervals[b][0] >= intervals[a][1]:
                    break
                v.violations.append(Violation(
                    "EMPLOYEE_OVERLAP", f"{intervals[a][2]},{intervals[b][2]}",
                    f"overlap on employee {eid}: [{intervals[a][0]},{intervals[a][1]}] and "
                    f"[{intervals[b][0]},{intervals[b][1]}]"))

    # precedence
    for order_id, routing in dataset.routings.items():
        for k in range(1, len(routing.operations)):
            prev, cur = routing.operations[k - 1], routing.operations[k]
            if prev in by_id and cur in by_id:
                if by_id[cur]["start"] < by_id[prev]["end"]:
                    v.violations.append(Violation(
                        "PRECEDENCE", f"{prev}->{cur}",
                        f"start({cur})={by_id[cur]['start']} < end({prev})={by_id[prev]['end']}"))

    # recompute completion / tardiness and compare with schedule.orders
    order_records = {r["order_id"]: r for r in orders}
    for order_id, routing in dataset.routings.items():
        if order_id not in order_records:
            v.violations.append(Violation("MISSING_ORDER", order_id, "order record missing"))
            continue
        last = routing.operations[-1]
        if last not in by_id:
            continue
        order = dataset.orders[order_id]
        completion = by_id[last]["end"]
        tardiness = max(0, completion - order.due_time)
        rec = order_records[order_id]
        if rec["completion_time"] != completion:
            v.violations.append(Violation(
                "COMPLETION_MISMATCH", order_id,
                f"reported completion {rec['completion_time']} != computed {completion}"))
        if rec["tardiness"] != tardiness:
            v.violations.append(Violation(
                "TARDINESS_MISMATCH", order_id,
                f"reported tardiness {rec['tardiness']} != computed {tardiness}"))

    # material consumption (Phase 5 Part 3): time-phased cumulative working
    # stock derived independently from the schedule and the BOMs must never
    # exceed on-hand inventory
    for mid, (required, available, shortage) in _material_shortages(dataset, by_id).items():
        v.violations.append(Violation(
            "MATERIAL_VIOLATION", mid,
            f"committed {required:.1f} of {mid} but only {available:.1f} on-hand "
            f"(short {shortage:.1f})",
            details={"material_id": mid, "required": required,
                     "available": available, "shortage": shortage}))

    v.valid = not v.violations
    return v
