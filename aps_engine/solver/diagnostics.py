"""Phase 4 Part 2 + Phase 6 Part 5: infeasibility diagnostics.

Phase 4 Part 2 (``build_diagnostics``): bounded layered analysis invoked when
CP-SAT returns INFEASIBLE. It does NOT relax or weaken any constraint and it
does NOT prove an exact mathematical root cause: each layer reports only
PROVEN necessary-condition violations. If every local check passes but the
model is still infeasible, the honest answer is GLOBAL_SCHEDULING_CONFLICT.

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

Phase 6 Part 5 (``analyze_infeasibility``): a thin post-solve root-cause layer
that consumes the layered diagnostics plus additional deterministic evidence
(machine capacity, maintenance/downtime windows, sequence setup/changeover
overhead) and ranks the detected causes into a single deterministic root
cause. It never relaxes a constraint, never runs a solver and never overrides
the Phase 4 diagnostics: it only maps and ranks them. When no cause is proven
the honest answer is UNKNOWN_INFEASIBILITY.
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Dict, List, Optional, Tuple

from aps_engine.models import Dataset, changeover
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


# ===========================================================================
# Phase 6 Part 5: post-solve feasibility root-cause analysis.
#
# A deterministic layer on top of ``build_diagnostics`` (and the additional
# evidence checks below). It returns a structured report and never modifies
# the Phase 4 diagnostics list.
# ===========================================================================

CAPACITY_SHORTAGE = "CAPACITY_SHORTAGE"
MACHINE_CAPACITY = CAPACITY_SHORTAGE  # alias for the same category
CALENDAR_LIMITATION = "CALENDAR_LIMITATION"
MAINTENANCE_DOWNTIME = "MAINTENANCE_DOWNTIME"
SETUP_CHANGEOVER_BURDEN = "SETUP_CHANGEOVER_BURDEN"
STRUCTURAL_INVALIDITY = "STRUCTURAL_INVALIDITY"
UNKNOWN_INFEASIBILITY = "UNKNOWN_INFEASIBILITY"

# Phase 4 / greedy diagnostic codes -> P5 root-cause categories. Codes not
# listed here (UNKNOWN_ORDER, UNKNOWN_MACHINE, DUPLICATE_OPERATION,
# INVALID_*, ...) are precise structural data errors and map to
# STRUCTURAL_INVALIDITY.
_P4_TO_P5 = {
    MACHINE_SHORTAGE: CAPACITY_SHORTAGE,
    EMPLOYEE_SHORTAGE: EMPLOYEE_SHORTAGE,
    SKILL_SHORTAGE: EMPLOYEE_SHORTAGE,
    WORK_CENTER_SHORTAGE: EMPLOYEE_SHORTAGE,
    EMPLOYEE_AVAILABILITY: EMPLOYEE_SHORTAGE,
    CALENDAR_CONFLICT: CALENDAR_LIMITATION,
    HORIZON_CONFLICT: CALENDAR_LIMITATION,
    PRECEDENCE_CONFLICT: CALENDAR_LIMITATION,
    MATERIAL_SHORTAGE: MATERIAL_SHORTAGE,
    GLOBAL_SCHEDULING_CONFLICT: UNKNOWN_INFEASIBILITY,
    "SCHEDULING_FAILURE": UNKNOWN_INFEASIBILITY,  # greedy reference solver
}
_KNOWN_P4_CODES = frozenset(_P4_TO_P5)

# Deterministic severity ranking: a lower rank number is the more fundamental
# cause and is reported first. Structural data errors outrank inventory, then
# staffing, then machine capacity, then machine blocking, then the planning
# window, then sequence setup overhead, and finally the honest UNKNOWN
# fallback.
_RANK = {
    STRUCTURAL_INVALIDITY: 1,
    MATERIAL_SHORTAGE: 2,
    EMPLOYEE_SHORTAGE: 3,
    CAPACITY_SHORTAGE: 4,
    MAINTENANCE_DOWNTIME: 5,
    CALENDAR_LIMITATION: 6,
    SETUP_CHANGEOVER_BURDEN: 7,
    UNKNOWN_INFEASIBILITY: 8,
}

# Confidence reflects proof strength: HIGH means the category is a PROVEN
# necessary-condition violation of the model; MEDIUM covers per-operation
# eligibility signals that still depend on assignment freedom; LOW means no
# cause was proven. Deterministic per category.
_CONFIDENCE = {
    STRUCTURAL_INVALIDITY: "HIGH",
    MATERIAL_SHORTAGE: "HIGH",
    CALENDAR_LIMITATION: "HIGH",
    CAPACITY_SHORTAGE: "HIGH",
    MAINTENANCE_DOWNTIME: "HIGH",
    SETUP_CHANGEOVER_BURDEN: "HIGH",
    EMPLOYEE_SHORTAGE: "MEDIUM",
    UNKNOWN_INFEASIBILITY: "LOW",
}


def _horizon(ds: Dataset) -> int:
    return ds.meta.get("horizon_end", 100_000)


def _known_machines(ds: Dataset, op) -> List[str]:
    return [mid for mid in op.allowed_machine_ids if mid in ds.machines]


def _machine_working_time(ds: Dataset, horizon: int) -> int:
    """Factory working minutes available to every machine (the calendar)."""
    slots = _working_slots(ds)
    if not slots:
        return horizon  # no calendar -> backward-compatible 24/7 availability
    return sum(s1 - s0 for _, s0, s1 in slots)


def _exclusive_ops_by_machine(ds: Dataset) -> Dict[str, List]:
    """Operations that can run on exactly one known machine, grouped by it.

    Only exclusive operations can prove a per-machine capacity, maintenance
    or setup shortage: an operation that may use several machines cannot
    prove that a single machine is the bottleneck.
    """
    by_machine: Dict[str, List] = {mid: [] for mid in ds.machines}
    for op in ds.operations.values():
        known = _known_machines(ds, op)
        if len(known) == 1:
            by_machine[known[0]].append(op)
    return by_machine


def _longest_slot(ds: Dataset, horizon: int) -> int:
    """Longest working slot length; ``horizon`` when there is no calendar."""
    slots = _working_slots(ds)
    return max((s1 - s0 for _, s0, s1 in slots), default=horizon)


def _capacity_evidence(ds: Dataset, horizon: int) -> Dict:
    """Proven machine capacity shortages.

    Per machine: the total processing time of its exclusive operations exceeds
    the machine's calendar working time. Aggregated: total processing demand
    of every operation exceeds total machine working time (n_machines x
    calendar minutes). Both are necessary conditions of feasibility.

    Only operations that individually fit a working slot are counted: an
    operation longer than every slot is a calendar limitation, not a machine
    capacity shortage.
    """
    longest = _longest_slot(ds, horizon)
    schedulable = lambda op: op.processing_time <= longest
    evidence: Dict = {}
    available = _machine_working_time(ds, horizon)
    for mid, ops in sorted(_exclusive_ops_by_machine(ds).items()):
        fit = [op for op in ops if schedulable(op)]
        if not fit:
            continue
        total = sum(op.processing_time for op in fit)
        if total > available:
            evidence.setdefault("machines", {})[mid] = {
                "required": total,
                "available": available,
                "operations": sorted(op.id for op in fit),
            }
    total_demand = sum(op.processing_time for op in ds.operations.values()
                       if schedulable(op))
    total_capacity = len(ds.machines) * available
    if total_demand > total_capacity:
        evidence["aggregate"] = {"required": total_demand,
                                 "available": total_capacity}
    return evidence


def _longest_free_window(ds: Dataset, mid: str) -> Optional[int]:
    """Longest maintenance/downtime-free contiguous interval on a machine.

    Computed from the factory working slots minus the machine's fixed
    maintenance and downtime windows. None when there is no calendar (24/7).
    """
    slots = _working_slots(ds)
    if not slots:
        return None
    blocked = sorted(
        [(w.start, w.end) for w in ds.maintenance if w.machine_id == mid]
        + [(w.start, w.end) for w in ds.downtime if w.machine_id == mid])
    longest = 0
    for _, s0, s1 in slots:
        free = [(s0, s1)]
        for bs, be in blocked:
            nxt = []
            for fs, fe in free:
                if be <= fs or bs >= fe:
                    nxt.append((fs, fe))
                else:
                    if bs > fs:
                        nxt.append((fs, bs))
                    if be < fe:
                        nxt.append((be, fe))
            free = nxt
        for fs, fe in free:
            longest = max(longest, fe - fs)
    return longest


def _maintenance_evidence(ds: Dataset, horizon: int) -> Dict:
    """Proven maintenance/downtime shortages.

    An exclusive operation that fits a plain working slot but cannot fit any
    maintenance/downtime-free window on its only machine proves that the fixed
    windows block the schedule.
    """
    evidence: Dict = {}
    slots = _working_slots(ds)
    longest_slot = max((s1 - s0 for _, s0, s1 in slots), default=0)
    for mid, ops in sorted(_exclusive_ops_by_machine(ds).items()):
        if not ops or not slots:
            continue
        longest_free = _longest_free_window(ds, mid)
        if longest_free is None:
            continue
        for op in sorted(ops, key=lambda o: o.id):
            if op.processing_time > longest_slot:
                continue  # calendar limitation, not maintenance
            if op.processing_time > longest_free:
                evidence.setdefault("machines", {})[mid] = {
                    "longest_free_window": longest_free,
                    "operation": op.id,
                    "needed": op.processing_time,
                }
                break  # one operation per machine is enough evidence
    return evidence


def _min_sequence_setup(ds: Dataset, ops: List) -> int:
    """Exact minimum changeover overhead to run ``ops`` on one machine.

    The first operation on a machine pays no setup (mirroring the solver);
    every later operation pays the changeover from its predecessor. Returns
    the minimum over all orderings, or a sound lower bound for large sets.
    """
    if len(ops) < 2:
        return 0
    if len(ops) > 7:
        min_in = [
            min([op.setup_time] + [changeover(ds, q, op)
                                   for q in ops if q.id != op.id])
            for op in ops]
        return sum(min_in) - max(min_in)
    best = None
    for perm in itertools.permutations(ops):
        total = 0
        prev = None
        for op in perm:
            if prev is not None:
                total += changeover(ds, prev, op)
            prev = op
        if best is None or total < best:
            best = total
    return best


def _setup_evidence(ds: Dataset, horizon: int) -> Dict:
    """Proven setup/changeover burden.

    For a machine whose exclusive operations fit by processing time alone but
    whose minimum possible changeover overhead pushes the workload past the
    machine's calendar working time, the setup/changeover requirement is the
    cause. Capacity overflows are left to CAPACITY_SHORTAGE (more
    fundamental).
    """
    evidence: Dict = {}
    longest = _longest_slot(ds, horizon)
    schedulable = lambda op: op.processing_time <= longest
    available = _machine_working_time(ds, horizon)
    for mid, ops in sorted(_exclusive_ops_by_machine(ds).items()):
        fit = [op for op in ops if schedulable(op)]
        if len(fit) < 2:
            continue
        total_proc = sum(op.processing_time for op in fit)
        if total_proc > available:
            continue  # capacity shortage is the more fundamental cause
        min_setup = _min_sequence_setup(ds, fit)
        if min_setup <= 0:
            continue
        if total_proc + min_setup > available:
            evidence.setdefault("machines", {})[mid] = {
                "processing": total_proc,
                "min_changeover": min_setup,
                "available": available,
                "operations": sorted(op.id for op in fit),
            }
    return evidence


def _describe(root: str, ranked, ds: Dataset, diagnostics: List[Dict],
              capacity: Dict, maintenance: Dict, setup: Dict) -> List[str]:
    """Concise, human-readable detail lines for the primary root cause."""
    lines: List[str] = []
    if root == STRUCTURAL_INVALIDITY:
        first = next(
            (d for d in diagnostics if d.get("code") not in _KNOWN_P4_CODES),
            None)
        if first is not None:
            lines.append(
                f"the dataset contains structural data errors "
                f"({len(diagnostics)} diagnostic(s)); first: "
                f"{first['code']}: {first['reason']}")
        else:
            lines.append(f"the dataset contains structural data errors "
                         f"({len(diagnostics)} diagnostic(s))")
    elif root == MATERIAL_SHORTAGE:
        shortages = _material_shortages(ds)
        total = sum(s for _, _, _, s in shortages)
        parts = ", ".join(f"{mid} short {s:.1f}" for mid, _, _, s in shortages)
        lines.append(
            f"order-book material demand exceeds on-hand inventory "
            f"({total:.1f} unit(s) short across {len(shortages)} material(s))"
            + (f": {parts}" if parts else ""))
    elif root == EMPLOYEE_SHORTAGE:
        lines.append(
            "no qualified and available employee can cover the operations "
            "that require staff (skill, work-center, shift or availability)")
    elif root == CAPACITY_SHORTAGE:
        parts = [
            f"{mid} needs {ev['required']} min of work but only "
            f"{ev['available']} working minutes are available"
            for mid, ev in sorted(capacity.get("machines", {}).items())]
        agg = capacity.get("aggregate")
        if agg:
            parts.append(f"total demand {agg['required']} min exceeds total "
                         f"machine capacity {agg['available']} min")
        lines.append("insufficient machine capacity: " + "; ".join(parts))
    elif root == MAINTENANCE_DOWNTIME:
        parts = [
            f"{mid} longest maintenance-free window is "
            f"{ev['longest_free_window']} min, below operation "
            f"{ev['operation']} needing {ev['needed']} min"
            for mid, ev in sorted(maintenance.get("machines", {}).items())]
        lines.append("maintenance/downtime blocks the machines: "
                     + "; ".join(parts))
    elif root == CALENDAR_LIMITATION:
        lines.append(
            "the factory calendar / planning horizon does not offer enough "
            "working time for the operations (slot length, horizon or "
            "precedence chain)")
    elif root == SETUP_CHANGEOVER_BURDEN:
        parts = [
            f"{mid} processing {ev['processing']} min plus minimum changeover "
            f"{ev['min_changeover']} min exceeds {ev['available']} min "
            f"available"
            for mid, ev in sorted(setup.get("machines", {}).items())]
        lines.append("setup/changeover overhead makes the workload "
                     "infeasible: " + "; ".join(parts))
    else:  # UNKNOWN_INFEASIBILITY
        lines.append(
            "no proven root cause: all local eligibility and capacity checks "
            "pass but the solver found no feasible schedule")
    if len(ranked) > 1:
        others = ", ".join(c for c, _ in ranked[1:])
        lines.append(f"secondary causes: {others}")
    return lines


def analyze_infeasibility(ds: Dataset,
                          diagnostics: Optional[List[Dict]] = None) -> Dict:
    """Phase 6 P5 root-cause analysis of an infeasible dataset.

    Consumes the layered diagnostics (computed via ``build_diagnostics`` when
    not supplied, e.g. the solver's ``SolveResult.diagnostics``) and adds
    deterministic machine-capacity, maintenance/downtime and
    setup/changeover evidence, then ranks every detected cause by severity.

    Returns a dict with:
      status       "INFEASIBLE", or "FEASIBLE" when ``diagnostics`` is empty
      root_cause   the highest-ranked category (None when FEASIBLE)
      confidence   HIGH / MEDIUM / LOW, deterministic per category
      rank         deterministic severity order of the root cause
      details      concise human-readable lines
      metrics      supporting evidence (capacity/maintenance/setup/counts)
      causes       all detected categories sorted by rank
      diagnostics  the underlying layered diagnostics (unchanged input)

    The API is usable independently of the CLI; it never runs a solver and
    never modifies its inputs.
    """
    horizon = _horizon(ds)
    if diagnostics is None:
        diagnostics = build_diagnostics(ds)
    if not diagnostics:
        return {
            "status": "FEASIBLE",
            "root_cause": None,
            "confidence": None,
            "rank": None,
            "details": ["no infeasibility diagnostics: the dataset is feasible"],
            "metrics": {},
            "causes": [],
            "diagnostics": [],
        }

    causes: Counter = Counter()
    for d in diagnostics:
        code = d.get("code", "")
        causes[_P4_TO_P5.get(code, STRUCTURAL_INVALIDITY)] += 1

    capacity = _capacity_evidence(ds, horizon)
    if capacity:
        causes[CAPACITY_SHORTAGE] += 1

    maintenance = _maintenance_evidence(ds, horizon)
    if maintenance:
        causes[MAINTENANCE_DOWNTIME] += 1

    setup = _setup_evidence(ds, horizon)
    if setup:
        causes[SETUP_CHANGEOVER_BURDEN] += 1

    # The UNKNOWN fallback is only honest when nothing else was proven.
    if UNKNOWN_INFEASIBILITY in causes and len(causes) > 1:
        del causes[UNKNOWN_INFEASIBILITY]

    ranked = sorted(causes.items(), key=lambda kv: _RANK[kv[0]])
    root = ranked[0][0]

    return {
        "status": "INFEASIBLE",
        "root_cause": root,
        "confidence": _CONFIDENCE[root],
        "rank": _RANK[root],
        "details": _describe(root, ranked, ds, diagnostics,
                             capacity, maintenance, setup),
        "metrics": {
            "capacity": capacity,
            "maintenance": maintenance,
            "setup": setup,
            "counts": dict(causes),
        },
        "causes": [{"category": c, "count": n, "rank": _RANK[c]}
                   for c, n in ranked],
        "diagnostics": diagnostics,
    }
