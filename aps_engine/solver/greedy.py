"""Phase 6 deterministic greedy reference scheduler.

A small, dependency-light list scheduler that mirrors the CP-SAT model's
constraints with a stable, fully deterministic algorithm. It never calls
CP-SAT and never mutates the Dataset (inventory is only read, never
reserved or consumed).

Strategy (documented so the behaviour is predictable and testable):

  1. Dispatch. Orders are processed one at a time in a stable order
     ``(release_time, due_time, order_id)``. Each order's production chain is
     scheduled as a compact block and the next order starts only after the
     current chain has finished (full order serialization). This trades
     concurrency for simplicity: with only one chain in the factory at a
     time, the committed working stock of any material at any instant is
     exactly one order's demand.

  2. Material gate. Under serialization the time-phased working-stock rule
     (Phase 5 Part 3) holds if and only if every single order's material
     demand fits within on-hand inventory for every material. Each order is
     therefore checked up front; an order whose demand exceeds on-hand for
     any material can never run (not even alone) and makes the dataset
     infeasible.

  3. Operation placement. Each operation is placed at the earliest feasible
     (machine, working slot, employee) triple:
       * allowed machines are tried in sorted id order;
       * the earliest start honours precedence (start >= previous chain
         operation's end) and the order's release time;
       * machine readiness: no overlap with previous work on the machine, a
         setup gap of ``op.setup_time`` after the machine's previous
         operation and after every maintenance / downtime window;
       * calendar: the operation fits entirely inside one working shift slot;
       * employee: the first (sorted id) eligible employee whose shifts match
         the slot, whose availability window contains the operation, and who
         has no overlapping prior work.
     Sequence-dependent setup matrices are out of scope here (Phase 4
     territory); the machine gap uses ``op.setup_time`` exactly as the
     validator checks it.

  4. Result. When every operation of every order is placed the result is a
     complete, validator-clean schedule with status FEASIBLE (a heuristic,
     never claimed optimal) and the same objective metric as the CP-SAT
     model: sum(order.priority * tardiness(order)). When any order fails its
     material gate or any operation cannot be placed, the result is
     INFEASIBLE with ``schedule=None`` and one diagnostics entry per
     recorded failure. Deterministic: identical inputs produce identical
     outputs.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from aps_engine.models import Dataset, Operation
from aps_engine.solver.model import SolveResult


def _working_slots(ds: Dataset) -> List[Tuple[Optional[str], int, int]]:
    """Chronological ``(shift_id, start, end)`` working slots.

    Mirrors the CP-SAT model's calendar handling: a dataset without shifts or
    calendar degrades to a single 24/7 slot with no shift id. A calendar that
    offers no working time yields an empty list (nothing can ever be placed).
    """
    if not ds.shifts or not ds.calendar:
        return [(None, 0, ds.meta.get("horizon_end", 100_000))]
    slots: List[Tuple[Optional[str], int, int]] = []
    for day in sorted(ds.calendar, key=lambda d: d.day_index):
        if not day.is_working:
            continue
        day_start = day.day_index * 1440
        for sid in day.shift_ids:
            sh = ds.shifts.get(sid)
            if sh is None:
                continue
            slots.append((sid, day_start + sh.start_minute,
                          day_start + sh.end_minute))
    slots.sort(key=lambda s: (s[1], s[2]))
    return slots


def _windows_of(ds: Dataset, mid: str) -> List[Tuple[int, int]]:
    """Chronological fixed unavailability windows for a machine."""
    windows = [(w.start, w.end) for w in ds.maintenance if w.machine_id == mid]
    windows += [(w.start, w.end) for w in ds.downtime if w.machine_id == mid]
    windows.sort()
    return windows


def _machine_ready(ds: Dataset, op: Operation, mid: str,
                   windows: List[Tuple[int, int]], start_after: int,
                   machine_free: Dict[str, int],
                   machine_used: Dict[str, bool]) -> int:
    """Earliest window-free start ``>= start_after`` on machine ``mid``.

    Respects the setup gap after the machine's previous operation
    (``op.setup_time``) and after every maintenance / downtime window: the
    region [start - setup, start + processing) must never overlap a window.
    """
    setup = op.setup_time
    start = start_after
    if machine_used[mid]:
        start = max(start, machine_free[mid] + setup)
    while True:
        pushed = False
        for ws, we in windows:
            if start - setup < we and ws < start + op.processing_time:
                start = we + setup
                pushed = True
                break
        if not pushed:
            return start


def _pick_employee(ds: Dataset, op: Operation, sid: Optional[str],
                   start: int, end: int,
                   employee_free: Dict[str, int]) -> Optional[str]:
    """First eligible employee for an operation, or None.

    Eligibility: required skill, work-center authorization, shift
    compatibility with the operation's slot, availability window, and no
    overlapping prior work (mirrors the CP-SAT model's checks).
    """
    for eid in sorted(ds.employees):
        emp = ds.employees[eid]
        if op.required_skill_id not in emp.skill_ids:
            continue
        if op.work_center_id not in emp.work_center_ids:
            continue
        if emp.available_from > start or end > emp.available_until:
            continue
        if sid is not None and sid not in emp.shift_ids:
            continue
        if employee_free[eid] > start:
            continue
        return eid
    return None


def _place_operation(ds: Dataset, op: Operation, slots,
                     windows_by_machine: Dict[str, List[Tuple[int, int]]],
                     machine_free: Dict[str, int],
                     machine_used: Dict[str, bool],
                     employee_free: Dict[str, int],
                     earliest_base: int
                     ) -> Optional[Tuple[str, int, int, Optional[str]]]:
    """Place ``op`` at the earliest feasible start.

    Returns ``(machine_id, start, end, employee_id)`` or ``None`` when no
    machine / working slot / eligible employee combination works. Reads but
    never mutates the placement state.
    """
    for mid in sorted(op.allowed_machine_ids):
        windows = windows_by_machine.get(mid, [])
        for sid, s0, s1 in slots:
            cand = _machine_ready(ds, op, mid, windows,
                                  max(earliest_base, s0),
                                  machine_free, machine_used)
            if cand + op.processing_time > s1:
                continue  # does not fit inside this working slot
            if not op.employee_required:
                return mid, cand, cand + op.processing_time, None
            eid = _pick_employee(ds, op, sid, cand, cand + op.processing_time,
                                 employee_free)
            if eid is not None:
                return mid, cand, cand + op.processing_time, eid
    return None


def greedy_solve(dataset: Dataset) -> Dict:
    """Deterministic greedy reference schedule (see module docstring).

    Returns ``{"result": SolveResult, "schedule": dict-or-None}`` mirroring
    ``solver.solve()``. On success ``result`` has status FEASIBLE and
    ``schedule`` is a complete, validator-clean schedule; on failure the
    status is INFEASIBLE, ``schedule`` is None and ``result.diagnostics``
    lists the recorded failures. The Dataset is never mutated.
    """
    ds = dataset
    t0 = time.monotonic()
    slots = _working_slots(ds)
    windows_by_machine = {mid: _windows_of(ds, mid) for mid in ds.machines}
    machine_free: Dict[str, int] = {mid: 0 for mid in ds.machines}
    machine_used: Dict[str, bool] = {mid: False for mid in ds.machines}
    employee_free: Dict[str, int] = {eid: 0 for eid in ds.employees}

    orders = sorted(ds.orders.values(),
                    key=lambda o: (o.release_time, o.due_time, o.id))
    scheduled: Dict[str, Dict] = {}
    failures: List[str] = []
    chain_end = 0  # serialization barrier: the next order starts after this

    for order in orders:
        # material gate: an order that cannot run alone can never run
        for mid, qty in ds.material_demand(order.id).items():
            if qty <= 0:
                continue
            record = ds.inventory_of(mid)
            on_hand = record.on_hand if record is not None else 0.0
            if qty > on_hand:
                failures.append(
                    f"order {order.id} needs {qty:.1f} of {mid} "
                    f"but only {on_hand:.1f} on-hand")
                break
        if failures:
            break
        order_end = chain_end
        for op in ds.operations_of_order(order.id):
            placed = _place_operation(
                ds, op, slots, windows_by_machine, machine_free, machine_used,
                employee_free, max(order.release_time, order_end))
            if placed is None:
                failures.append(
                    f"order {order.id} operation {op.id} could not be placed")
                break
            mid, start, end, eid = placed
            scheduled[op.id] = {
                "operation_id": op.id,
                "order_id": op.order_id,
                "machine_id": mid,
                "employee_id": eid,
                "start": start,
                "end": end,
            }
            machine_free[mid] = end
            machine_used[mid] = True
            if eid is not None:
                employee_free[eid] = end
            order_end = end
        if failures:
            break
        chain_end = order_end

    wall = time.monotonic() - t0
    if failures:
        return {
            "result": SolveResult(
                status="INFEASIBLE",
                status_code=cp_model.INFEASIBLE,
                feasible=False,
                objective_value=None,
                best_bound=None,
                num_conflicts=0,
                num_branches=0,
                wall_time=wall,
                diagnostics=[{"code": "SCHEDULING_FAILURE", "message": f}
                             for f in failures],
            ),
            "schedule": None,
        }

    order_records = []
    objective = 0.0
    for order in ds.orders.values():
        last = ds.routings[order.id].operations[-1]
        completion = scheduled[last]["end"]
        tardiness = max(0, completion - order.due_time)
        objective += order.priority * tardiness
        order_records.append({
            "order_id": order.id,
            "completion_time": completion,
            "due_time": order.due_time,
            "tardiness": tardiness,
        })
    operations = [scheduled[op_id] for op_id in ds.operations]
    return {
        "result": SolveResult(
            status="FEASIBLE",
            status_code=cp_model.FEASIBLE,
            feasible=True,
            objective_value=float(objective),
            best_bound=None,
            num_conflicts=0,
            num_branches=0,
            wall_time=wall,
            diagnostics=[],
        ),
        "schedule": {
            "operations": operations,
            "orders": order_records,
            "objective_value": float(objective),
        },
    }
