"""Phase 3 CP-SAT scheduling model.

Core constraints:

  1. operation precedence        start(O2) >= end(O1) within a routing
  2. machine compatibility       exactly one allowed machine per operation
  3. machine capacity            NoOverlap per machine (optional intervals)
  4. release time                start >= order release_time
  5. factory calendar            each operation fits entirely inside exactly
                                 one working shift slot (start and end in the
                                 same shift, never on a holiday)
  6. machine availability        maintenance / downtime windows are fixed
                                 NoOverlap intervals on their machine
  7. machine setup (changeover)  between any ordered pair of activities on a
                                machine the gap must be >= the changeover of
                                that pair (sequence-independent setup_time by
                                default; sequence-dependent when the operation
                                carries a setup_family_id and the dataset
                                defines a setup_matrix). No setup before the
                                machine's first operation; maintenance and
                                downtime windows also block setup.
  8. employee assignment         exactly one eligible employee per operation
     - skill                     employee.skill_ids contains required skill
     - work-center authorization operation work center in employee.work_center_ids
     - shift compatibility       employee's shift matches the operation's slot
     - availability              available_from <= start, end <= available_until
     - capacity                  NoOverlap on optional employee intervals
  9. due date                    soft, expressed as weighted tardiness objective
   10. material availability      time-phased: on-hand inventory of each
                                  material is a cumulative capacity that orders
                                  draw on for the whole duration of their
                                  production chain (start of first operation to
                                  end of last), so committed working-stock
                                  never exceeds on-hand at any instant and
                                  orders sharing a scarce material interact in
                                  time

Objective (single):  min sum(order.priority * tardiness(order))
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from aps_engine.models import Dataset, Operation, changeover
from aps_engine.objectives import get_objective
from aps_engine.solver.diagnostics import build_diagnostics


@dataclass
class SolverParams:
    time_limit_seconds: int = 30
    num_search_workers: int = 2
    random_seed: int = 42
    log_search_progress: bool = False
    objective: str = "weighted_tardiness"


class ModelBuilder:
    def __init__(self, ds: Dataset, params: Optional[SolverParams] = None):
        self.ds = ds
        self.p = params or SolverParams()
        self.model = cp_model.CpModel()
        self.horizon_end = ds.meta.get("horizon_end", 100_000)
        self.solver: Optional[cp_model.CpSolver] = None
        self.wall_time: float = 0.0

        self.on_im: Dict[Tuple[str, str], cp_model.IntVar] = {}
        self.start_im: Dict[Tuple[str, str], cp_model.IntVar] = {}
        self.end_im: Dict[Tuple[str, str], cp_model.IntVar] = {}
        self.start_i: Dict[str, cp_model.IntVar] = {}
        self.end_i: Dict[str, cp_model.IntVar] = {}
        self.machine_ops: Dict[str, List[str]] = {}
        self.tardiness: Dict[str, cp_model.IntVar] = {}
        self.makespan_var: Optional[cp_model.IntVar] = None
        # shift slots derived from the factory calendar:
        # (day_index, shift_id, start_abs, end_abs)
        self.slots: List[Tuple[int, str, int, int]] = []
        # per-operation shift-slot selection booleans, aligned with self.slots
        self.slot_selection: Dict[str, List[cp_model.IntVar]] = {}
        # employee assignment: on_e[(op_id, eid)], employee_iv[(op_id, eid)]
        self.on_e: Dict[Tuple[str, str], cp_model.IntVar] = {}
        self.employee_iv: Dict[Tuple[str, str], cp_model.IntervalVar] = {}

    # ------------------------------------------------------------------ build
    def build(self) -> "ModelBuilder":
        self._declare_vars()
        self._calendar()
        self._machine_capacity()
        self._employees()
        self._precedence()
        self._release()
        self._material_availability()
        self._objective()
        return self

    def _declare_vars(self) -> None:
        m = self.model
        for op_id, op in self.ds.operations.items():
            for mid in op.allowed_machine_ids:
                on = m.NewBoolVar(f"on_{op_id}_{mid}")
                s = m.NewIntVar(0, self.horizon_end, f"s_{op_id}_{mid}")
                e = m.NewIntVar(0, self.horizon_end, f"e_{op_id}_{mid}")
                m.NewOptionalIntervalVar(s, op.processing_time, e, on, f"iv_{op_id}_{mid}")
                self.on_im[(op_id, mid)] = on
                self.start_im[(op_id, mid)] = s
                self.end_im[(op_id, mid)] = e
                self.machine_ops.setdefault(mid, []).append(op_id)
            sg = m.NewIntVar(0, self.horizon_end, f"s_{op_id}")
            eg = m.NewIntVar(0, self.horizon_end, f"e_{op_id}")
            self.start_i[op_id] = sg
            self.end_i[op_id] = eg
            for mid in op.allowed_machine_ids:
                m.Add(sg == self.start_im[(op_id, mid)]).OnlyEnforceIf(self.on_im[(op_id, mid)])
                m.Add(eg == self.end_im[(op_id, mid)]).OnlyEnforceIf(self.on_im[(op_id, mid)])
            m.AddExactlyOne([self.on_im[(op_id, mid)] for mid in op.allowed_machine_ids])

    def _calendar(self) -> None:
        """Force every operation into exactly one working shift slot.

        If the dataset has no calendar, the model degrades to 24/7
        availability (backward compatible with Phase 1 style datasets).
        """
        ds = self.ds
        if not ds.shifts or not ds.calendar:
            return
        slots: List[Tuple[int, str, int, int]] = []
        for day in sorted(ds.calendar, key=lambda d: d.day_index):
            if not day.is_working:
                continue
            day_start = day.day_index * 1440
            for sid in day.shift_ids:
                sh = ds.shifts.get(sid)
                if sh is None:
                    continue
                slots.append((day.day_index, sid,
                              day_start + sh.start_minute, day_start + sh.end_minute))
        slots.sort(key=lambda s: s[2])
        if not slots:
            return
        self.slots = slots

        m = self.model
        for op_id in sorted(ds.operations):
            sel = [m.NewBoolVar(f"shift_{op_id}_{i}") for i in range(len(slots))]
            m.AddExactlyOne(sel)
            self.slot_selection[op_id] = sel
            for i, (_, _, s0, s1) in enumerate(slots):
                m.Add(self.start_i[op_id] >= s0).OnlyEnforceIf(sel[i])
                m.Add(self.end_i[op_id] <= s1).OnlyEnforceIf(sel[i])

    def _machine_activities(self, mid: str) -> List[Tuple[object, object, object]]:
        """All activities of a machine: its candidate operations (optional)
        plus the fixed maintenance / downtime windows, as (obj, start, end)
        tuples. start/end are IntVars for operations and ints for windows."""
        acts: List[Tuple[object, object, object]] = []
        for op_id in sorted(set(self.machine_ops[mid])):
            op = self.ds.operations[op_id]
            acts.append((op, self.start_im[(op_id, mid)], self.end_im[(op_id, mid)]))
        for w in self.ds.maintenance:
            if w.machine_id == mid:
                acts.append((w, w.start, w.end))
        for w in self.ds.downtime:
            if w.machine_id == mid:
                acts.append((w, w.start, w.end))
        return acts

    @staticmethod
    def _activity_name(obj) -> str:
        if isinstance(obj, Operation):
            return obj.id
        return f"win_{obj.reason}_{obj.start}"

    def _machine_capacity(self) -> None:
        """Machine capacity via a pairwise disjunctive model.

        Each machine owns a set of activities: the candidate operations
        (optional intervals, active only when the operation is assigned to
        this machine) plus the fixed maintenance / downtime windows. A single
        ``AddNoOverlap`` over the plain processing intervals prevents overlap,
        and for each unordered pair of activities an ordering literal enforces
        the sequence-dependent changeover gap via ``changeover()``.

        When no setup family / setup matrix data is present this reproduces
        the Phase 5 extended-interval behaviour exactly (the changeover of a
        pair is simply the following operation's ``setup_time``); when the
        data is present the pair-dependent changeover applies.
        """
        for mid in self.machine_ops:
            acts = self._machine_activities(mid)
            intervals = []
            for obj, start, end in acts:
                if isinstance(obj, Operation):
                    intervals.append(self.model.NewOptionalIntervalVar(
                        start, obj.processing_time, end,
                        self.on_im[(obj.id, mid)], f"mach_{mid}_{obj.id}"))
                else:
                    intervals.append(self.model.NewIntervalVar(
                        obj.start, obj.end - obj.start, obj.end,
                        f"{obj.reason}_{mid}_{obj.start}"))
            if intervals:
                self.model.AddNoOverlap(intervals)
            self._add_setup_pairs(mid, acts)

    def _add_setup_pairs(self, mid: str, acts) -> None:
        """Pairwise changeover constraints between activities on one machine.

        For each unordered pair (i, j) whose changeover is non-zero in at
        least one direction, a BoolVar ordering literal selects which activity
        runs first and the corresponding changeover gap is enforced. The
        constraints are gated on machine assignment: an operation-operation
        pair binds only when BOTH operations are actually assigned to this
        machine (``on_im``), and an operation-window pair binds only when the
        operation is assigned to this machine (the window itself is always
        active). A pair touching an operation scheduled on another machine
        imposes no temporal constraint here. Pairs with a zero gap in both
        directions need no literal (NoOverlap already separates them).

        The operation-to-operation changeover and the post-maintenance setup
        are INDEPENDENT lower bounds: both always apply, the stronger of the
        two binds, and they are never summed across a window.
        """
        m = self.model
        n = len(acts)
        for a in range(n):
            for b in range(a + 1, n):
                obj_a, s_a, e_a = acts[a]
                obj_b, s_b, e_b = acts[b]
                gap_ab = changeover(self.ds, obj_a, obj_b)
                gap_ba = changeover(self.ds, obj_b, obj_a)
                if gap_ab == 0 and gap_ba == 0:
                    continue
                seq = m.NewBoolVar(
                    f"seq_{mid}_{self._activity_name(obj_a)}_{self._activity_name(obj_b)}")
                gates = []
                if isinstance(obj_a, Operation):
                    gates.append(self.on_im[(obj_a.id, mid)])
                if isinstance(obj_b, Operation):
                    gates.append(self.on_im[(obj_b.id, mid)])
                m.Add(s_b >= e_a + gap_ab).OnlyEnforceIf([seq] + gates)
                m.Add(s_a >= e_b + gap_ba).OnlyEnforceIf([seq.Not()] + gates)

    def _employees(self) -> None:
        """Joint employee assignment: exactly one eligible employee per op.

        Eligibility is enforced statically (skill + work-center + duration
        fits the availability window) and dynamically (the selected employee's
        shift must match the operation's chosen slot, and the operation must
        fall inside the employee's availability window). Employee capacity is
        enforced with NoOverlap on optional intervals sharing the operation's
        start/end.
        """
        ds = self.ds
        if not ds.employees:
            return
        m = self.model
        for op_id, op in sorted(ds.operations.items()):
            if not op.employee_required:
                continue
            candidates = []
            for eid, emp in sorted(ds.employees.items()):
                if op.required_skill_id not in emp.skill_ids:
                    continue
                if op.work_center_id not in emp.work_center_ids:
                    continue
                if emp.available_until - emp.available_from < op.processing_time:
                    continue
                candidates.append(eid)
            if not candidates:
                m.AddBoolOr([])  # infeasible: required employee has no candidates
                continue
            emp_vars: Dict[str, Tuple[cp_model.IntVar, cp_model.IntervalVar]] = {}
            for eid in candidates:
                b = m.NewBoolVar(f"on_e_{op_id}_{eid}")
                iv = m.NewOptionalIntervalVar(
                    self.start_i[op_id], op.processing_time, self.end_i[op_id],
                    b, f"emp_iv_{op_id}_{eid}")
                emp_vars[eid] = (b, iv)
            m.AddExactlyOne([b for b, _ in emp_vars.values()])
            for eid, (b, iv) in emp_vars.items():
                emp = ds.employees[eid]
                # shift compatibility: the operation's slot must use one of the
                # employee's shifts (skip when there is no calendar at all)
                if self.slots:
                    sel_in_emp = [self.slot_selection[op_id][i]
                                  for i, (_, sid, _, _) in enumerate(self.slots)
                                  if sid in emp.shift_ids]
                    if sel_in_emp:
                        m.Add(sum(sel_in_emp) == 1).OnlyEnforceIf(b)
                    else:
                        m.Add(b == 0)
                # availability window
                m.Add(self.start_i[op_id] >= emp.available_from).OnlyEnforceIf(b)
                m.Add(self.end_i[op_id] <= emp.available_until).OnlyEnforceIf(b)
                self.on_e[(op_id, eid)] = b
                self.employee_iv[(op_id, eid)] = iv

        # employee capacity: no two operations of the same employee overlap
        by_emp: Dict[str, List[cp_model.IntervalVar]] = {}
        for (op_id, eid), iv in self.employee_iv.items():
            by_emp.setdefault(eid, []).append(iv)
        for eid, intervals in by_emp.items():
            if len(intervals) > 1:
                m.AddNoOverlap(intervals)

    def _precedence(self) -> None:
        for order_id, routing in self.ds.routings.items():
            ops = routing.operations
            for k in range(1, len(ops)):
                prev, cur = ops[k - 1], ops[k]
                self.model.Add(self.start_i[cur] >= self.end_i[prev])

    def _release(self) -> None:
        for order_id, order in self.ds.orders.items():
            for op_id in self.ds.routings[order_id].operations:
                self.model.Add(self.start_i[op_id] >= order.release_time)

    def _material_availability(self) -> None:
        """Time-phased material availability as a cumulative constraint.

        For each material the on-hand inventory is a capacity that orders draw
        on for the whole duration of their production chain: an order commits
        its full material demand (from its BOM) from the start of its first
        operation until the end of its last operation. ``AddCumulative``
        enforces that the committed working-stock quantity never exceeds the
        on-hand inventory at any instant, so orders sharing a scarce material
        interact in time: they cannot be in production simultaneously beyond
        the available stock. Demand and capacity are scaled to integers (x100)
        so fractional BOM quantities stay exact. Consumption happens only
        inside the solver model (never reserved or allocated on the Dataset),
        and datasets without BOMs / material demand are unaffected.
        """
        ds = self.ds
        if not ds.boms:
            return
        m = self.model
        scale = 100
        for material_id in sorted(ds.materials):
            record = ds.inventory_of(material_id)
            capacity = int(round((record.on_hand if record else 0.0) * scale))
            intervals = []
            demands = []
            for order_id in sorted(ds.orders):
                requirement = ds.material_demand(order_id).get(material_id, 0.0)
                if requirement <= 0:
                    continue
                routing = ds.routings.get(order_id)
                if routing is None or not routing.operations:
                    continue
                first, last = routing.operations[0], routing.operations[-1]
                size = m.NewIntVar(0, self.horizon_end,
                                   f"mat_sz_{material_id}_{order_id}")
                intervals.append(m.NewIntervalVar(
                    self.start_i[first], size, self.end_i[last],
                    f"mat_iv_{material_id}_{order_id}"))
                demands.append(int(round(requirement * scale)))
            if intervals:
                m.AddCumulative(intervals, demands, capacity)

    def _objective(self) -> None:
        get_objective(self.p.objective)(self)

    # ------------------------------------------------------------------ solve
    def solve(self) -> "SolveResult":
        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = self.p.time_limit_seconds
        self.solver.parameters.num_search_workers = self.p.num_search_workers
        self.solver.parameters.random_seed = self.p.random_seed
        self.solver.parameters.log_search_progress = self.p.log_search_progress
        t0 = time.monotonic()
        status = self.solver.Solve(self.model)
        self.wall_time = time.monotonic() - t0
        feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        result = SolveResult(
            status=self.solver.status_name(status),
            status_code=status,
            feasible=feasible,
            objective_value=self.solver.ObjectiveValue() if feasible else None,
            best_bound=self.solver.BestObjectiveBound() if feasible else None,
            num_conflicts=self.solver.NumConflicts(),
            num_branches=self.solver.NumBranches(),
            wall_time=self.wall_time,
        )
        if not feasible:
            result.diagnostics = build_diagnostics(self.ds)
        return result


@dataclass
class SolveResult:
    status: str
    status_code: int
    feasible: bool
    objective_value: Optional[float]
    best_bound: Optional[float]
    num_conflicts: int
    num_branches: int
    wall_time: float
    diagnostics: List[Dict] = field(default_factory=list)

    @property
    def optimal(self) -> bool:
        return self.status_code == cp_model.OPTIMAL


def extract_schedule(ds: Dataset, result: SolveResult, builder: ModelBuilder) -> Dict:
    """Extract the simple serializable schedule."""
    sv = builder.solver
    m = builder.model
    employee_of = {op_id: eid for (op_id, eid), b in builder.on_e.items()
                   if sv.Value(b) == 1}
    operations = []
    for op_id, op in ds.operations.items():
        machine = None
        for mid in op.allowed_machine_ids:
            if sv.Value(builder.on_im[(op_id, mid)]) == 1:
                machine = mid
                break
        operations.append({
            "operation_id": op_id,
            "order_id": op.order_id,
            "machine_id": machine,
            "employee_id": employee_of.get(op_id),
            "start": int(sv.Value(builder.start_i[op_id])),
            "end": int(sv.Value(builder.end_i[op_id])),
        })
    orders = []
    for order_id, order in ds.orders.items():
        last = ds.routings[order_id].operations[-1]
        completion = int(sv.Value(builder.end_i[last]))
        orders.append({
            "order_id": order_id,
            "completion_time": completion,
            "due_time": order.due_time,
            "tardiness": max(0, completion - order.due_time),
        })
    return {
        "operations": operations,
        "orders": orders,
        "objective_value": result.objective_value,
    }
