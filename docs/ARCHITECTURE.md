# APS Engine Architecture

Deterministic synthetic-data APS engine built on OR-Tools CP-SAT. Time is
integer minutes since the start of day 0.

## Domain architecture (`aps_engine/models/domain.py`)

- `Dataset` — root container: products, orders, operations, routings,
  work centers, machines, skills, employees, shifts, calendar, maintenance,
  downtime, materials, BOMs, inventory, and a global `setup_matrix`
  ({(from_family, to_family): minutes}).
- `Order` -> `product_id`, quantity, release_time, due_time, priority.
- `Product` -> `Routing` (ordered list of operation ids).
- `Operation` -> work_center, allowed_machine_ids, processing_time,
  setup_time, setup_family_id, required_skill_id, employee_required.
- `WorkCenter` -> machine_ids; `Machine` -> work_center_id.
- `Employee` -> shift_ids, skill_ids, work_center_ids, available_from/until.
- `Shift` / `CalendarDay` — shift bounds in minutes-since-midnight; per-day
  working flag + shift list.
- `MaintenanceWindow` / `DowntimeWindow` — fixed absolute-minute blocks.
- `Material` -> id/name/unit; `BOM` -> `BomItem` (quantity per unit of a
  material) per product; `MaterialInventory` -> `on_hand`. The read-only
  domain layer exposes `material_demand(order_id)`,
  `material_requirements(product, qty)` and `order_book_material_feasibility()`;
  it never consumes, reserves or allocates stock.
- `changeover(ds, prev, nxt)` — the single source of truth for setup gaps:
  matrix value when both ops have families and a matrix exists, else the
  following operation's `setup_time`; `any -> window` is 0; `window -> op`
  is the operation's `setup_time`.

## Solver / model (`aps_engine/solver/`)

- `model.py` — `ModelBuilder` adds all constraints, then `solve()` runs
  CP-SAT; `extract_schedule()` serializes the solution.
- Decision variables: `on_im` (machine assignment), `start_im`/`end_im`
  (per-machine), `start_i`/`end_i` (per-operation), shift-slot selection,
  employee assignment `on_e` + optional intervals, per-order tardiness.
- Material availability: time-phased cumulative constraint per material —
  each order commits its full BOM demand (`material_demand`) for the whole
  duration of its production chain (start of first op to end of last op),
  and `AddCumulative` keeps the committed working stock at or below on-hand
  inventory at every instant. Demand/capacity are scaled x100 so fractional
  BOM quantities stay exact. Consumption is modeled inside CP-SAT only; the
  `Dataset` is never mutated.
- Machine capacity: one `AddNoOverlap` of plain optional intervals per
  machine plus per-pair ordering literals (`seq`) enforcing the
  sequence-dependent changeover gap; each pair is gated on the `on_im`
  literals of the operations involved.
- `solver.py` — thin orchestration: build -> solve -> extract.
- `diagnostics.py` — layered infeasibility diagnostics run only when CP-SAT
  reports INFEASIBLE; never modifies constraints; falls back to
  `GLOBAL_SCHEDULING_CONFLICT`.

## Validator (`aps_engine/validation/validator.py`)

Independent post-solve check that re-derives every rule from the
`(dataset, schedule)` pair without inspecting the CP-SAT model: precedence,
machine compatibility, machine overlap, setup gap, release time, calendar
(same-shift containment, no holidays), maintenance/downtime avoidance,
employee assignment, recomputed completion/tardiness, and time-phased material
consumption (each order commits its BOM demand for its whole production chain;
peak committed working stock per material must not exceed on-hand, reported as
`MATERIAL_VIOLATION` with material_id / required / available / shortage).
Returns `ValidationResult(valid, violations)` with typed violation codes.

## Pre-solve (`aps_engine/validation/pre_solve.py`)

Structural validation run before CP-SAT: unknown references, zero compatible
resources, impossible availability, horizon overflows. Not a feasibility
proof — a clean pre-solve with an INFEASIBLE model is a global scheduling
conflict.

## Generator (`aps_engine/generator/generator.py`)

Deterministic dataset builder (seed 42): 10 orders, 5 products, 4 work
centers, 8 machines, 3-5 ops/order, 14-day calendar (Mon-Fri two shifts,
Sat morning, Sun + one extra holiday), 4 maintenance + 2 downtime windows,
9 employees (CNC is a genuine bottleneck), plus a bill-of-materials /
inventory layer. The default dataset is deliberately material-short (order
book cannot be produced from current stock); `generate_dataset(
material_feasible=True)` raises on-hand inventory to exactly cover the order
book. Also `generate_infeasible_dataset()` for the diagnostics E2E path.

## CLI (`aps_engine/cli/main.py`)

Pipeline: generate -> build -> solve -> extract -> validate -> report.
Exit 0 on feasible/valid, exit 1 on infeasible or invalid. Prints orders,
operations, employee counts, validation report (including a
material (MATERIAL_VIOLATION) count), a changeover/setup summary, and the
read-only `[8] MATERIAL FEASIBILITY` report. `--infeasible` solves the
deterministic infeasible dataset; `--material-feasible` uses the
material-feasible dataset variant.

## Data flow

```
generator.generate_dataset()
  -> Dataset
  -> ModelBuilder.build()          (adds all CP-SAT constraints)
  -> builder.solve()               (CP-SAT, 30s limit, seed 42)
  -> extract_schedule()            (operations/orders/objective)
  -> validator.validate()          (independent re-check)
  -> CLI report / exit code
```

## Major constraints (solver/model.py)

1. Precedence: `start(next) >= end(prev)` within each routing.
2. Machine compatibility: exactly one allowed machine per operation.
3. Machine capacity: `NoOverlap` per machine (optional intervals).
4. Release time: `start >= order.release_time`.
5. Factory calendar: operation fits entirely inside one working shift slot.
6. Machine availability: maintenance/downtime are fixed intervals.
7. Setup/changeover: ordered pair gap >= `changeover()` value, gated on
   machine assignment.
8. Employee assignment: exactly one eligible employee (skill, work center,
   shift, availability), `NoOverlap` per employee.
9. Material availability: time-phased cumulative working stock per material,
   `AddCumulative` <= on-hand at every instant (scaled x100).
10. Due date: soft, via the objective.

## Current objective

Single objective, minimize `sum(order.priority * tardiness(order))`, where
`tardiness = max(0, end(last_op) - due_time)`.
