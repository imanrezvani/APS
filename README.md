# APS Engine — Phase 8 Persistence & Service API, Phase 9 HTTP/Application API

A minimal but correct CP-SAT production scheduler for a wood-panel / furniture
factory. Phase 5 adds machine setup (changeover) times on top of the Phase 4
joint machine + employee assignment: every production operation is assigned to
one compatible machine, one qualified employee and one valid factory calendar
slot, and consecutive operations on a machine must be separated by the setup
time of the following operation. Since Phase 4.4, products also carry a bill of
materials (BOM) backed by a read-only inventory model, and since Phase 5 the
solver enforces time-phased material availability while the independent
validator re-derives material consumption from the schedule.

Phase 6 adds a deterministic greedy reference scheduler and a benchmark harness
(`solve` vs `greedy_solve`), makes the setup gap sequence-dependent through
per-product setup families plus a global `setup_matrix` (single source of truth
`changeover()`), and adds a deterministic feasibility root-cause analysis
(`analyze_infeasibility`) on top of the layered diagnostics, printed as
`Root cause: <CAUSE>` by the CLI.

Phase 7 makes the solver objective pluggable: the objective is extracted from
`ModelBuilder` into a registry (`aps_engine.objectives`) of builder callables,
with `weighted_tardiness` as the default and a deterministic `makespan`
alternative, selectable through `SolverParams.objective` or the CLI
`--objective` flag.

Phase 8 productionizes the engine without changing its scheduling behaviour:
datasets and solve results persist losslessly as versioned JSON documents
(`aps_engine.io`), a thin programmatic facade
(`aps_engine.api.plan`) exposes a stable service boundary over the solver
without leaking CP-SAT internals, and a `aps-engine` console entry point is
installed alongside `python -m aps_engine`.

Phase 9 adds a thin HTTP/Application API boundary around that service-ready
core: a dedicated `aps_api` FastAPI package exposes `GET /health`,
`GET /version` and `POST /plans` (submit a Phase 8 dataset JSON document and
receive a JSON-safe ResultDocument-compatible response). The HTTP layer never
contains solver logic — routes delegate to `aps_engine.api.plan()` through an
application/service boundary. There is no database, frontend/Gantt,
multi-tenancy, authentication, async worker queue or deployment layer yet.

## Scope

The engine enforces:

| Constraint                 | Enforced |
|----------------------------|----------|
| Operation precedence       | yes      |
| Machine compatibility      | yes      |
| Machine capacity           | yes (NoOverlap) |
| Machine setup / changeover | yes (gap >= `changeover()` value; sequence-dependent with setup families) |
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
| Due date                   | soft → objective (default weighted tardiness) |

## Objective

The solver objective is pluggable through `aps_engine/objectives` — a registry
that maps objective names to builder callables. `ModelBuilder` delegates
objective construction via `SolverParams.objective` (default
`weighted_tardiness`). Registered objectives:

- `weighted_tardiness` (default): `minimize sum(order.priority * tardiness(order))`
- `makespan`: `minimize max(end_time over all operations)`

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

Since Phase 6 the setup gap may be sequence-dependent: each product carries an
optional `setup_family_id` and the dataset a global `setup_matrix`
(`{(from_family, to_family): minutes}`). The gap between two consecutive
activities on a machine is `changeover(ds, prev, nxt)` — the matrix value when
both operations have families and a matrix entry exists, otherwise the
following operation's `setup_time` (`any -> window` is 0, `window -> op` is the
operation's `setup_time`). Without setup families the behavior is identical to
the sequence-independent case, so Phase 1-5 datasets behave exactly as before.
`changeover()` is the single source of truth shared by the CP-SAT model, the
independent validator and the CLI setup summary.

## Reference scheduler & benchmark

`solver/greedy.py` provides a deterministic greedy reference scheduler
(`greedy_solve`) that mirrors the CP-SAT feasibility model (machines, calendar,
maintenance, employees, materials, sequence-dependent setup) by scheduling
orders one at a time. It returns the same `SolveResult` shape and objective
metric as CP-SAT but never claims optimality — it is an independent cross-check
checked by the same validator. `aps_engine.benchmarks`
(`python -m aps_engine.benchmarks`) runs `solve` and `greedy_solve` on the same
Dataset and reports status, objective, wall time, operations scheduled and
independent validity for each, asserting neither solver mutates the Dataset.

## Persistence & service API

Phase 8 exposes a versioned, machine-readable layer over the existing engine
(`aps_engine/io/` and `aps_engine/api.py`). It adds no scheduling behaviour.

**Dataset JSON persistence** — `aps_engine.io.dataset_io`:
`dataset_to_json(dataset)` serializes a `Dataset` into a versioned JSON
document (`aps-engine.dataset.v1`) and `dataset_from_json(data)` rebuilds it
losslessly (accepting a JSON string or a parsed dict). The round trip
preserves the whole domain graph — `meta`, products/orders/operations/
routings, work centers/machines, skills/employees/shifts/calendar,
maintenance/downtime, materials/BOMs/inventory — including the tuple-keyed
`setup_matrix`, whose `(from_family, to_family)` keys are encoded as explicit
`[from, to, minutes]` triples so
`generate_dataset(sequence_dependent_setup=True)` round-trips exactly.
Reconstructed datasets are deep-equal to the original and solve identically.

**Result / schedule JSON persistence** — `aps_engine.io.result_io`:
`result_to_json(output)` / `result_from_json(data)` round-trip a solve output
(`SolveResult` status, status code, objective value, diagnostics, plus the
schedule) as a versioned document (`aps-engine.result.v1`); diagnostics carry
the root-cause information when an infeasible solve produced it. The raw
CP-SAT `builder` is never serialized. `save_result(output, path)` and
`load_result(path)` are the file helpers.

**Service API facade** — `aps_engine.api`:
`plan(dataset_or_doc, objective="weighted_tardiness", params=None)` returns a
`ResultDocument` (`{"result": SolveResult, "schedule": ...}`) from either an
existing `Dataset` or a P1 dataset JSON document (string or parsed dict). The
objective is validated against the registry (unknown names raise the same
`KeyError` as the CLI, before any model build) and the returned document is
exactly the P2 persistence representation, so it can be stored verbatim with
`save_result`. Raw `ModelBuilder` / `CpModel` / `CpSolver` / `IntVar` objects
are never exposed. `plan` and `ResultDocument` are re-exported from
`aps_engine`.

```python
from aps_engine import plan
from aps_engine.generator import generate_dataset
from aps_engine.io import dataset_to_json, save_result

ds = generate_dataset(material_feasible=True, sequence_dependent_setup=True)
doc = plan(ds, objective="makespan")          # dataset input
doc2 = plan(dataset_to_json(ds))              # P1 JSON document input
save_result(doc, "data/results/plan.json")    # P2 file persistence
```

## HTTP API (Phase 9)

A dedicated FastAPI application package (`aps_api`) wraps the Phase 8 service
facade. It is importable without starting a server
(`from aps_api import app`, or build a fresh instance with `create_app()`)
and is suitable for future deployment, but Phase 9 ships no deployment
configuration.

### Start the API locally

```bash
# FastAPI / uvicorn are installed as part of `pip install -e .[dev]`.
python -m uvicorn aps_api.app:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI docs: http://127.0.0.1:8000/docs

### Endpoints

| Method | Path      | Purpose |
|--------|-----------|---------|
| GET    | `/health` | Liveness probe: `{"status": "ok", "service": "aps-engine"}` |
| GET    | `/version`| `{"name": "aps-engine", "version": "<pyproject version>"}` — read from the single package version source (`importlib.metadata`), never duplicated |
| POST   | `/plans`  | Submit a Phase 8 dataset JSON document and receive the planning result |

### Health and version

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/version
```

### Create a plan

`POST /plans` accepts a JSON body whose `dataset` field is a dataset document
in the exact Phase 8 persistence format (the object produced by
`dataset_to_json(dataset)`). The `objective` is optional (default
`weighted_tardiness`; `makespan` is the other registered objective) and an
optional `params` object may override the deterministic solver settings
(`time_limit_seconds` 1-3600 default 30, `num_search_workers` 1-32 default 2,
`random_seed` default 42).

```bash
# Generate a dataset document once and post it
python - <<'PY'
import json
from aps_engine.generator import generate_dataset
from aps_engine.io import dataset_to_json
json.dump(json.loads(dataset_to_json(
    generate_dataset(material_feasible=True, sequence_dependent_setup=True))),
    open("/tmp/dataset.json", "w"))
PY

curl -s -X POST http://127.0.0.1:8000/plans \
  -H "Content-Type: application/json" \
  -d @/tmp/dataset.json
```

Equivalent with an explicit objective and solver params:

```bash
curl -s -X POST http://127.0.0.1:8000/plans \
  -H "Content-Type: application/json" \
  -d '{
    "dataset": <dataset document>,
    "objective": "makespan",
    "params": {"time_limit_seconds": 30, "num_search_workers": 2, "random_seed": 42}
  }'
```

### Request / response behaviour

The response is JSON-serializable and compatible with the Phase 8
ResultDocument semantics:

```json
{
  "result": {
    "status": "OPTIMAL",
    "status_code": 0,
    "feasible": true,
    "objective_value": 1350.0,
    "best_bound": 1350.0,
    "num_conflicts": 0,
    "num_branches": 0,
    "wall_time": 1.23,
    "diagnostics": []
  },
  "schedule": {
    "operations": [{"operation_id": "OP000", "order_id": "ORD000",
                    "machine_id": "...", "employee_id": "...",
                    "start": 480, "end": 540}],
    "orders": [{"order_id": "ORD000", "completion_time": 900,
                "due_time": 960, "tardiness": 0}],
    "objective_value": 1350.0
  }
}
```

No CP-SAT model objects, solver internals or non-serializable enums are ever
exposed. Validation happens before planner execution: an invalid objective or
dataset document never reaches the solver.

### Infeasibility semantics

An infeasible production plan is a **valid planning result**, not an API or
server failure. A valid request whose dataset cannot be scheduled returns
**HTTP 200** with `schedule: null`, `result.status: "INFEASIBLE"`,
`result.feasible: false` and the engine's layered diagnostics preserved in
`result.diagnostics` (rows with `code`, `order_id`, `operation_id`,
`resource_type`, `resource_id`, `reason`). Root-cause codes such as
`MATERIAL_SHORTAGE`, `EMPLOYEE_SHORTAGE`, `CAPACITY_SHORTAGE`,
`CALENDAR_LIMITATION`, `MAINTENANCE_DOWNTIME`, `SETUP_CHANGEOVER_BURDEN`,
`STRUCTURAL_INVALIDITY` and `UNKNOWN_INFEASIBILITY` are carried through
unchanged; the API never turns solver infeasibility into an HTTP 500.

### Invalid requests

Every non-2xx response uses the same structured envelope
`{"error": {"code", "message", "details"?}}` and never leaks a stack trace:

| Status | Error code                 | Meaning |
|--------|----------------------------|---------|
| 400    | `INVALID_DATASET_DOCUMENT` | `dataset` is not a valid Phase 8 dataset document |
| 400    | `UNKNOWN_OBJECTIVE`        | objective not in the registry (lists valid names) |
| 422    | `VALIDATION_ERROR`         | malformed JSON / schema violation (`details` lists the fields) |
| 404    | `HTTP_404`                 | unknown route |
| 500    | `INTERNAL_ERROR`           | unexpected internal failure (no internal detail exposed) |

```bash
curl -s -X POST http://127.0.0.1:8000/plans \
  -H "Content-Type: application/json" \
  -d '{"dataset": {"orders": []}, "objective": "does_not_exist"}'
# -> 400 {"error":{"code":"UNKNOWN_OBJECTIVE","message":"unknown objective
#     'does_not_exist' (valid: makespan, weighted_tardiness)"}}
```

### Application boundary & async readiness

`aps_api/executor.py` introduces a minimal `PlanExecutor` abstraction
(`SyncPlanExecutor` today). The routes call
`aps_api.service.PlanningService.create_plan`, which delegates to the
executor, which calls `aps_engine.api.plan()`. Because the executor is
injectable (also via `create_app(service=...)`), a future phase can evolve
synchronous `POST /plans` execution into job creation -> worker -> result
retrieval without rewriting the routes or the APS Engine. Phase 9 implements
**no** async worker, job queue, Celery/Redis or message broker.

### Phase 9 does NOT yet provide

Authentication, a database, multi-tenancy, a frontend/Gantt UI, async
workers/job queues, or a production deployment. Only the thin synchronous
HTTP boundary described above is implemented.

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
    solver/greedy.py      # deterministic greedy reference scheduler
    solver/diagnostics.py # infeasibility diagnostics (Phase 4) + root-cause analysis (Phase 6 P5)
    objectives/           # pluggable objective registry (weighted_tardiness, makespan)
    io/dataset_io.py      # Dataset JSON persistence (dataset_to_json / dataset_from_json)
    io/result_io.py       # result/schedule JSON persistence (result_to_json / result_from_json / save_result / load_result)
    api.py                # programmatic service facade (plan() -> ResultDocument)
    validation/pre_solve.py  # pre-solve structural validation (Phase 4)
    validation/validator.py  # independent post-solve validator
    benchmarks/           # benchmark harness (solve vs greedy_solve)
    cli/main.py           # CLI entry (aps-engine / python -m aps_engine)
aps_api/                 # Phase 9 FastAPI HTTP/Application boundary
    app.py                # create_app() -> FastAPI (/health, /version, /plans)
    version.py            # package version from importlib.metadata (single source)
    schemas.py            # Pydantic request/response/error contracts
    errors.py             # PlanningError + deterministic error envelope handlers
    executor.py           # PlanExecutor abstraction (SyncPlanExecutor)
    service.py            # PlanningService (thin service boundary)
    routes/plans.py       # POST /plans handler (delegates to the service)
    tests/
    test_generator.py
    test_validator.py
    test_solver.py
    test_setup.py
    test_diagnostics.py
    test_pre_solve.py
    test_cli_e2e.py
    test_api_http.py      # Phase 9 HTTP integration tests
    test_api_service.py   # Phase 9 service/executor/schema unit tests
```

## Install

```bash
pip install -e .[dev]
```

This registers the `aps-engine` console entry point (`pyproject.toml
[project.scripts]` → `aps_engine.cli.main:main`), so the CLI runs both as a
module and as an installed command.

## Run

Generate, solve, extract, validate and print the report:

```bash
python -m aps_engine
aps-engine
```

Exit codes: `0` for a feasible, validated schedule; `1` for an infeasible
dataset (feasibility diagnostics are printed) or a schedule that fails
validation. Solve a deterministic infeasible dataset to see the diagnostics
path:

```bash
python -m aps_engine --infeasible
```

Solve the material-feasible variant of the same dataset (solves to OPTIMAL
39.0, `valid: True violations: 0`, and exits 0):

```bash
python -m aps_engine --material-feasible
```

Select the solver objective (default `weighted_tardiness`; `makespan` is the
only other registered objective). The material-feasible variant solves to
OPTIMAL 39.0 under weighted tardiness and OPTIMAL 1350.0 under makespan:

```bash
python -m aps_engine --material-feasible --objective weighted_tardiness
python -m aps_engine --material-feasible --objective makespan
aps-engine --material-feasible --objective makespan
```

Compare the CP-SAT solver against the greedy reference scheduler:

```bash
python -m aps_engine.benchmarks
```

Run the tests:

```bash
python -m pytest
```

Run only the Phase 9 API tests:

```bash
python -m pytest tests/test_api_http.py tests/test_api_service.py
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

Phase 6 adds a deterministic root-cause layer on top:
`solver/diagnostics.py.analyze_infeasibility(ds, diagnostics)` consumes the
layered diagnostics plus additional evidence (machine capacity,
maintenance/downtime windows, minimum setup/changeover overhead) and ranks the
detected causes into a single root cause with a deterministic severity order:
`MATERIAL_SHORTAGE`, `CAPACITY_SHORTAGE` / `MACHINE_CAPACITY`,
`EMPLOYEE_SHORTAGE`, `CALENDAR_LIMITATION`, `MAINTENANCE_DOWNTIME`,
`SETUP_CHANGEOVER_BURDEN`, `STRUCTURAL_INVALIDITY`, `UNKNOWN_INFEASIBILITY`.
The CLI prints `Root cause: <CAUSE>` plus concise details on infeasible runs,
before the existing layered diagnostics.

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
- sequence-dependent setup families via `changeover()` (solver + validator +
  CLI setup summary); `setup_time = 0` preserves Phase 1-4 behaviour
- deterministic greedy reference scheduler agrees with CP-SAT on feasibility
  and passes the same independent validator
- benchmark harness reports solver vs greedy status, objective, wall time and
  validity without mutating the Dataset
- infeasible runs print a deterministic `Root cause: <CAUSE>` before the
  layered diagnostics
- pluggable objective registry (`weighted_tardiness` default, `makespan`
  registered); extracted builder reproduces the original objective exactly
  (material-feasible OPTIMAL 39.0)
- makespan solves the material-feasible dataset to OPTIMAL 1350.0 and is
  deterministic in objective value across repeated runs
- CLI `--objective` selects the objective and fails cleanly on invalid values
  (exit 1); default CLI output, exit codes and objective 39.0 are unchanged
- Phase 1 through Phase 9 tests pass (410)
- dataset and result/schedule JSON persistence round-trips losslessly
  (including the sequence-dependent `setup_matrix`); loaded schedules pass the
  validator
- `plan()` facade returns a persistable result document from a Dataset or its
  P1 JSON document without exposing CP-SAT internals, for both objectives
- `aps-engine` console entry point preserves CLI output and exit codes
- FastAPI application imports without starting a server; `/health` and
  `/version` work; `/version` reads the single package version source
- `POST /plans` accepts a Phase 8 dataset JSON document and returns a JSON-safe
  ResultDocument-compatible response for the default, `weighted_tardiness` and
  `makespan` objectives, without exposing CP-SAT/solver internals
- infeasible datasets return HTTP 200 with `schedule: null` and the engine's
  layered diagnostics preserved (never an HTTP 500); invalid requests return
  deterministic structured 4xx errors with no stack-trace leakage
- async-ready `PlanExecutor` boundary exists with no external queue
  infrastructure
- solver schedule passes validator
- CLI runs successfully
