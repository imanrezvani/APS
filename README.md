# APS Engine — Phase 5 Setup & Changeover

A minimal but correct CP-SAT production scheduler for a wood-panel / furniture
factory. Phase 5 adds machine setup (changeover) times on top of the Phase 4
joint machine + employee assignment: every production operation is assigned to
one compatible machine, one qualified employee and one valid factory calendar
slot, and consecutive operations on a machine must be separated by the setup
time of the following operation. Since Phase 4.4, products also carry a bill of
materials (BOM) backed by a read-only inventory model, and since Phase 5 the
solver enforces time-phased material availability while the independent
validator re-derives material consumption from the schedule.

## Scope

Phase 5 enforces:

| Constraint                 | Enforced |
|----------------------------|----------|
| Operation precedence       | yes      |
| Machine compatibility      | yes      |
| Machine capacity           | yes (NoOverlap) |
| Machine setup / changeover | yes (gap >= setup_time of the following operation) |
| Order release time         | yes      |
| Factory calendar           | yes (each operation fits inside one shift; no holidays) |
| Maintenance / downtime     | yes (fixed NoOverlap windows) |
| Employee assignment        | yes (exactly one per operation) |
| Required skill             | yes (employee must have the operation's skill) |
| Work-center authorization  | yes (employee authorized for the operation's work center) |
| Employee shift             | yes (employee assigned to the operation's shift) |
| Employee availability      | yes (available_from <= start, end <= available_until) |
| Employee capacity          | yes (NoOverlap on employee intervals) |
| Material availability      | yes (time-phased cumulative working stock, Phase 5) |
| Due date                   | soft → weighted tardiness objective |

Objective (single): `minimize sum(order.priority * tardiness(order))`

## Factory calendar

Default calendar (integer minutes, day 0 = Monday):

- Mon-Fri: Shift A 08:00-16:00, Shift B 16:00-24:00
- Saturday: Shift A only
- Sunday: holiday (off)
- day 3 (Thursday week 1): extra plant-wide holiday (off)

Every operation must start AND end inside the same working shift — it can
never cross a shift boundary and can never run on a holiday. Maintenance and
downtime windows are unavailability intervals added to a machine's
`AddNoOverlap` list.

## Setup / changeover

Every operation carries an optional `setup_time` (minutes to set up the
machine before the operation starts; default 0). Between two consecutive
activities on a machine the gap must be at least the `setup_time` of the
following operation — there is no setup before a machine's first operation.
Maintenance and downtime windows also block setup time (the machine is
unavailable for changeover during a break).

Modeling: the machine capacity `NoOverlap` uses an *extended* interval per
operation, `[start - setup_time, end)` with size `processing_time + setup_time`
instead of the plain processing interval. Two extended intervals can only be
non-overlapping if the later operation starts at least its setup time after
the earlier one ends. A `setup_time` of 0 makes the interval identical to the
plain one, so Phase 1-4 datasets behave exactly as before.

The independent validator re-derives the same rule from the schedule alone:
consecutive operations on a machine are checked with the `SETUP_VIOLATION`
code. Setup-induced infeasibility is a global scheduling conflict and, like
other unprovable combinations, is reported as `GLOBAL_SCHEDULING_CONFLICT` by
the diagnostics layer.

## Employees

Skills: `CUTTING`, `EDGE_BANDING`, `CNC`, `ASSEMBLY`. The dataset has 9
employees with different shift/skill/work-center combinations. Employee
resource contention is genuine: only 2 employees are CNC-qualified (one per
shift) while the dataset contains 6 CNC operations, so CNC work is a real
bottleneck. Edge banding B is unavailable on Monday, exercising availability.

Modeling: for each operation the solver picks exactly one eligible employee
(`on_e[op, emp]`). Eligibility is filtered statically (skill + work-center +
availability length) and enforced dynamically (the selected employee's shift
must match the operation's chosen calendar slot; the operation must fall
inside the employee's availability window). Employee capacity is a hard
`NoOverlap` over optional employee intervals that share the operation's
start/end.

## Materials

Products carry a bill of materials (`BOM` with `BomItem` entries, quantity per
unit), and `Dataset.inventory` records each material's `on_hand` stock. The
read-only domain layer computes per-order demand
(`material_demand(order_id)`) and the order-book feasibility check
(`order_book_material_feasibility()`); it never consumes, reserves or
allocates stock. `generate_dataset(material_feasible=True)` raises on-hand
inventory to exactly cover the whole order book so the scheduling constraints
can be exercised on a material-feasible dataset.

The solver enforces material availability as a time-phased cumulative
constraint: each order commits its full BOM demand for the whole duration of
its production chain (start of its first operation to end of its last), and
the committed working stock of a material never exceeds on-hand at any
instant, so orders sharing a scarce material must not be in production
simultaneously beyond the available stock. Consumption happens only inside the
CP-SAT model — the `Dataset` is never mutated.

The independent validator re-derives the same rule from the schedule and BOMs
alone (never inspecting CP-SAT): it reports `MATERIAL_VIOLATION` with
`material_id`, peak `required`, `available` (on-hand) and `shortage` when the
peak simultaneous committed quantity exceeds stock. The CLI prints the
validator's material status in the `[7] VALIDATION` section and the read-only
order-book report in `[8] MATERIAL FEASIBILITY`.

## Structure

```
aps_engine/
    models/domain.py      # Order, Operation, Routing, WorkCenter, Machine,
                          #   Shift, CalendarDay, MaintenanceWindow, DowntimeWindow,
                          #   Skill, Employee
    generator/generator.py# deterministic synthetic dataset (seed=42)
    solver/model.py       # CP-SAT model + extraction
    solver/solver.py      # solve() orchestration
    solver/diagnostics.py # infeasibility diagnostics (Phase 4)
    validation/pre_solve.py  # pre-solve structural validation (Phase 4)
    validation/validator.py  # independent post-solve validator
    cli/main.py           # CLI entry
    tests/
    test_generator.py
    test_validator.py
    test_solver.py
    test_setup.py
    test_diagnostics.py
    test_pre_solve.py
    test_cli_e2e.py
```

## Install

```bash
pip install -e .[dev]
```

## Run

Generate, solve, extract, validate and print the report:

```bash
python -m aps_engine
```

Exit codes: `0` for a feasible, validated schedule; `1` for an infeasible
dataset (feasibility diagnostics are printed) or a schedule that fails
validation. Solve a deterministic infeasible dataset to see the diagnostics
path:

```bash
python -m aps_engine --infeasible
```

Run the tests:

```bash
python -m pytest
```

## Dataset

Deterministic (seed=42), reproducible: 10 orders, 5 products, 4 work centers
(Cutting, Edge banding, CNC, Assembly), 8 machines, 9 employees, 4 skills,
3-5 operations per order, a 14-day factory calendar, 4 maintenance and 2
downtime windows. Every operation carries a per-skill setup time (CUTTING and
EDGE_BANDING 15 min, CNC 20 min, ASSEMBLY 10 min). Most operations have two
compatible machines and several eligible employees, so the joint
machine/employee assignment is a real optimization decision. The DESK assembly
operation runs only on ASM-1.

## Solver settings

- max time: 30 s
- num search workers: 2
- CP-SAT random seed: 42

## Pre-solve validation

`aps_engine.validation.pre_solve.pre_solve_validate(dataset)` runs before
CP-SAT and detects obvious structural impossibilities: unknown references
(machines, work centers, skills, shifts, employees, orders, operations),
zero compatible machines, zero qualified employees, impossible availability
windows, and horizon overflows. It returns a structured
`PreSolveValidationResult` (issues with code/severity/resource). It is NOT a
feasibility proof — if it passes but CP-SAT reports INFEASIBLE, the cause is
a global scheduling conflict.

## Infeasibility diagnostics

When CP-SAT reports `INFEASIBLE`, `solver/diagnostics.py` runs a bounded
layered analysis (structural pre-solve -> machine eligibility -> employee
eligibility -> employee availability -> calendar/precedence) and attaches the
result to `SolveResult.diagnostics` as a list of
`{code, order_id, operation_id, resource_type, resource_id, reason}`.
Categories: `MACHINE_SHORTAGE`, `EMPLOYEE_SHORTAGE`, `SKILL_SHORTAGE`,
`WORK_CENTER_SHORTAGE`, `EMPLOYEE_AVAILABILITY`, `CALENDAR_CONFLICT`,
`HORIZON_CONFLICT`, `PRECEDENCE_CONFLICT`, `MATERIAL_SHORTAGE`. If no local
root cause is proven,
the honest answer is `GLOBAL_SCHEDULING_CONFLICT`. Constraints are never
weakened to produce a diagnosis. Feasible runs have `diagnostics = []`.

## Acceptance gate

- machine setup / changeover constraint (solver + independent validator)
- backward compatible: `setup_time = 0` preserves Phase 1-4 behaviour
- employee + skill model
- skill, work-center, shift, availability, NoOverlap constraints
- joint machine + employee assignment
- independent validator (setup + employee + material + all Phase 1/2 checks)
- skill-bottleneck and shift-bottleneck solver proofs
- material-feasible dataset solves to OPTIMAL 39.0; material-short dataset is
  INFEASIBLE with MATERIAL_SHORTAGE diagnostics; validator flags material
  over-consumption with MATERIAL_VIOLATION details
- Phase 1, Phase 2, Phase 3, Phase 4 and Phase 5 tests pass
- solver schedule passes validator
- CLI runs successfully
