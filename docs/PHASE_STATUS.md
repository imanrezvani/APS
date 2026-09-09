# Phase Status

| Phase | Status |
| --- | --- |
| Phase 1 — baseline model (machines, precedence, objective) | COMPLETE |
| Phase 2 — factory calendar (shifts, holidays, maintenance, downtime) | COMPLETE |
| Phase 3 — employee assignment (skills, work centers, shifts, availability) | COMPLETE |
| Phase 4.1 — material + BOM domain models | COMPLETE |
| Phase 4.2 — inventory domain + generator data | COMPLETE |
| Phase 4.3 — BOM integration (generator BOMs + helpers) | COMPLETE |
| Phase 4.4 — material requirements + availability check | COMPLETE |
| Phase 4.5 P1 — material feasibility result layer | COMPLETE |
| Phase 4.5 P2 — production-order material feasibility | COMPLETE |
| Phase 4.6 P1 — order-book material feasibility | COMPLETE |
| Phase 4.6 P2 — material/BOM/inventory pre-solve integrity checks | COMPLETE |
| Phase 4.7 P1 — material demand interface (`material_demand` / `material_demands`) | COMPLETE |
| Phase 4.7 P2 — material-feasible dataset scenario | COMPLETE |
| Phase 4.7 P3 — CLI material feasibility report | COMPLETE |
| Phase 5 P1 — aggregate material availability constraint + MATERIAL_SHORTAGE diagnostics | COMPLETE |
| Phase 5 P2 — time-phased material consumption | COMPLETE |
| Phase 5 P3 — independent material validation + CLI/docs | COMPLETE |
| Phase 6 P1 — deterministic greedy reference scheduler | COMPLETE |
| Phase 6 P2 — benchmark harness (`solve` vs `greedy_solve`) | COMPLETE |
| Phase 6 P3 — documentation & housekeeping reconciliation | COMPLETE |
| Phase 6 P4 — sequence-dependent setup / changeover | COMPLETE |
| Phase 6 P5 — feasibility root-cause diagnostics | COMPLETE |
| Phase 7 P1 — objective extraction (pluggable objective registry) | COMPLETE |
| Phase 7 P2 — makespan objective | COMPLETE |
| Phase 7 P3 — CLI objective selection (`--objective`) | COMPLETE |
| Phase 7 P4 — documentation & housekeeping reconciliation | COMPLETE |
| Phase 8 P1 — dataset JSON persistence (`aps_engine/io`) | COMPLETE |
| Phase 8 P2 — result/schedule JSON persistence | COMPLETE |
| Phase 8 P3 — service API facade (`aps_engine.api.plan`) | COMPLETE |
| Phase 8 P4 — packaging & `aps-engine` console entry point | COMPLETE |
| Phase 8 P5 — documentation & reconciliation | COMPLETE |
| Phase 9 P1 — HTTP API foundation (FastAPI app, `/health`, `/version`) | COMPLETE |
| Phase 9 P2 — planning endpoint (`POST /plans`) | COMPLETE |
| Phase 9 P3 — API contracts (request/response schemas, deterministic 4xx) | COMPLETE |
| Phase 9 P4 — error & diagnostics contract (root-cause preservation) | COMPLETE |
| Phase 9 P5 — async-ready application boundary (executor abstraction) | COMPLETE |
| Phase 9 P6 — API integration tests | COMPLETE |
| Phase 9 P7 — documentation & reconciliation | COMPLETE |

## Current state

- Uniform pairwise disjunctive capacity model in `aps_engine/solver/model.py`:
  `NoOverlap` on plain processing intervals + per-pair ordering literals
  whose changeover gaps come from `changeover()`.
- Setup-pair constraints are gated on machine assignment (`on_im` of both
  involved operations), so a changeover on an unselected candidate machine
  does not constrain an operation scheduled on another compatible machine.
- Setup on a shared machine still binds; op->op changeover and post-maintenance
  setup act as independent lower bounds (never summed).
- Without setup-family data, `changeover()` reproduces the previous
  sequence-independent behaviour exactly (the following operation's
  `setup_time`).
- Two independent solvers: CP-SAT (`solve`) and a deterministic greedy
  reference scheduler (`greedy_solve`), both checked by the same independent
  validator, and a deterministic benchmark harness (`aps_engine.benchmarks`)
  that compares them on the same Dataset without mutating it.
- Infeasibility reporting is two-layered: the Phase 4 layered diagnostics
  (`build_diagnostics`) plus the Phase 6 P5 root-cause analysis
  (`analyze_infeasibility`) that ranks all detected causes (material,
  capacity, employee, calendar, maintenance/downtime, setup/changeover,
  structural, unknown) into a single deterministic root cause. The CLI prints
  `Root cause: <CAUSE>` on infeasible runs and still exits 1.
- The objective is pluggable (Phase 7): `aps_engine/objectives` is a registry
  mapping objective names to builder callables. `ModelBuilder` delegates
  objective construction through `SolverParams.objective` (default
  `weighted_tardiness`). Registered objectives: `weighted_tardiness`
  (`min sum(order.priority * tardiness(order))`, the original single
  objective) and `makespan` (`min max(end_time over all operations)`). The
  CLI selects the objective with `--objective <name>`.
- The engine is service-ready (Phase 8): a Dataset or a P1 dataset JSON
  document solves through the programmatic facade
  `aps_engine.api.plan(dataset_or_doc, objective=..., params=None)` which
  returns a machine-consumable result document (result + schedule; never the
  raw CP-SAT builder). Datasets round-trip losslessly through
  `aps_engine.io.dataset_io` (including the tuple-keyed `setup_matrix`), and
  solve results/schedules round-trip through `aps_engine.io.result_io` with
  explicit file helpers. The `aps-engine` console entry point
  (`pyproject.toml [project.scripts]`) is the installed equivalent of
  `python -m aps_engine`.
- The engine is now exposed through a thin HTTP/Application API boundary
  (Phase 9): a dedicated `aps_api` FastAPI package whose routes only delegate
  to the Phase 8 service facade through `aps_engine.api.plan()`. Endpoints:
  `GET /health` (liveness), `GET /version` (single source of truth from the
  package version / distribution metadata, never duplicated) and
  `POST /plans` (submit a Phase 8 dataset JSON document; default,
  `weighted_tardiness` and `makespan` objectives; returns a JSON-safe
  ResultDocument-compatible payload). An infeasible plan is a valid 200
  response (schedule `null` plus preserved layered diagnostics), invalid
  requests get a deterministic structured 4xx envelope, and solver/CP-SAT
  internals never leak into responses. A minimal `PlanExecutor` abstraction
  (`aps_api/executor.py`) prepares the boundary for a future async
  job/worker phase without adding queue infrastructure. There is still no
  frontend/Gantt, database, multi-tenancy, scenario/what-if, async workers,
  authentication, AI/Copilot or deployment layer.

## Tests / status

- Full suite: **410 passed, 0 failed, 0 skipped** (`python -m pytest`).
- Coverage: generator 9, validator 24, solver 20, setup 9, diagnostics 10,
  pre-solve 17, CLI E2E 2, sequence-dependent setup 24, material + BOM 13,
  inventory 11, BOM integration 17, material requirements 20,
  material feasibility 10, production-order material feasibility 7,
  order-book material feasibility 8, pre-solve materials 10, material demand 9,
  material-feasible scenario 8, CLI material report 5, generator setup
  families 5, greedy 15, benchmark 7, CLI setup summary 2, feasibility
  diagnostics 16, validator material 6, objectives 7, makespan 5, CLI
  objective 5, dataset IO 20, result IO 15, API facade 16, packaging 6,
  API service/executor/schema 16, API HTTP 22.
- Regression: `test_operation_assigned_elsewhere_not_constrained_by_candidate_pair`
  proves an op assigned to another machine is not constrained by an unselected
  machine's changeover (PANEL->FLAT = 100000, both ops still start at 480).
- CLI (`python -m aps_engine`): exit 1, `STATUS: INFEASIBLE`,
  `Root cause: MATERIAL_SHORTAGE`, material-shortage diagnostics preserved.
- CLI (`python -m aps_engine --material-feasible`): exit 0, `STATUS: OPTIMAL`,
  objective 39.0, `valid: True violations: 0`, `Employee violations: 0`,
  26 changeovers / 370 setup minutes.
- CLI (`python -m aps_engine --infeasible`): exit 1, `STATUS: INFEASIBLE`,
  `Root cause: EMPLOYEE_SHORTAGE`.
- CLI (`python -m aps_engine --material-feasible --objective weighted_tardiness`):
  exit 0, `STATUS: OPTIMAL`, `OBJECTIVE (weighted tardiness): 39.0`,
  `valid: True violations: 0` (same as the default objective).
- CLI (`python -m aps_engine --material-feasible --objective makespan`):
  exit 0, `STATUS: OPTIMAL`, `OBJECTIVE (makespan): 1350.0`,
  `valid: True violations: 0`; makespan is deterministic across repeated runs.
- CLI invalid objective (`--objective bogus`): exit 1, stderr
  `ERROR: unknown objective 'bogus' (valid: makespan, weighted_tardiness)`.
- CLI console entry point (`aps-engine`, installed via `pip install -e .`):
  byte-identical output and identical exit codes to
  `python -m aps_engine` for the feasible (exit 0), infeasible (exit 1),
  makespan (exit 0, `OBJECTIVE (makespan): 1350.0`) and invalid-objective
  (exit 1) paths.
- Persistence/API smoke: `plan()` on the Dataset and on its P1 JSON document
  returns OPTIMAL 39.0 (weighted_tardiness) / 1350.0 (makespan) documents
  that persist/load through `aps_engine.io.result_io` and whose loaded
  schedules validate with zero violations; the persisted result document
  contains no raw builder / CP-SAT object.
- Family-enabled consistency
  (`generate_dataset(sequence_dependent_setup=True, material_feasible=True)`):
  cp-sat OPTIMAL 39.0 / valid; greedy FEASIBLE 11550.0 / valid; feasibility
  agreement True.

## Completed phases

**Phase 5 — APS Solver** (COMPLETE): material constraints inside the CP-SAT
model, implemented through the standard staged workflow.

- **P1 (complete)** — aggregate material availability as a hard constraint
  plus a `MATERIAL_SHORTAGE` diagnostics layer: when the aggregate order-book
  demand of a material exceeds on-hand inventory the model is INFEASIBLE and
  the diagnostics report one MATERIAL_SHORTAGE per short material. Default
  dataset (material-short) is INFEASIBLE; `material_feasible=True` still
  solves to OPTIMAL 39.0. Tests in `tests/test_material_solver.py`.
- **P2 (complete)** — time-phased material consumption: each material's on-hand
  inventory is a cumulative capacity that orders draw on for the whole duration
  of their production chain (start of first operation to end of last). An order
  commits its full BOM demand from chain start to chain end and the committed
  working stock never exceeds on-hand at any instant. Demand and capacity are
  scaled x100 to keep fractional BOM quantities exact. Consumption happens only
  inside the solver model; the Dataset is never mutated. Default dataset stays
  INFEASIBLE and `material_feasible=True` still solves to OPTIMAL 39.0. Tests
  in `tests/test_material_consumption.py`.
- **P3 (complete)** — independent material validation + CLI/docs: the
  validator (`validation/validator.py`) re-derives time-phased material
  consumption from the schedule and BOMs alone (never inspecting CP-SAT);
  reported as `MATERIAL_VIOLATION` with material_id / required / available /
  shortage details. The feasible variant stays `valid: True`, 0 violations and
  the default material-short dataset stays INFEASIBLE with MATERIAL_SHORTAGE
  diagnostics (exit codes unchanged). Tests in
  `tests/test_validator_material.py`.

**Phase 6 — reference scheduler, setup families, diagnostics** (COMPLETE).

- **P1 (complete)** — deterministic greedy reference scheduler
  (`solver/greedy.py`, `greedy_solve`): a simple, deterministic scheduler that
  mirrors the CP-SAT feasibility model (machines, calendar, maintenance,
  employees, materials, sequence-dependent setup) so it can be used as an
  independent cross-check. Returns `SolveResult` + schedule; INFEASIBLE runs
  report one `SCHEDULING_FAILURE` diagnostic per failure. Tests in
  `tests/test_greedy.py`.
- **P2 (complete)** — benchmark harness (`benchmarks/comparison.py`,
  `python -m aps_engine.benchmarks`): runs `solve` and `greedy_solve` on the
  same Dataset and reports status, objective, wall time, operations scheduled
  and independent validity for each, asserting neither solver mutates the
  Dataset. Tests in `tests/test_benchmark.py`.
- **P3 (complete)** — documentation & housekeeping reconciliation: `README.md`
  and `docs/ARCHITECTURE.md` updated to cover the Phase 6 surface (greedy
  reference scheduler, benchmark harness, sequence-dependent setup families /
  `changeover()`, feasibility root-cause analysis) and the CLI module docstring
  moved to a phase-neutral "APS Engine CLI". Git hygiene: `.gitignore`
  added (`__pycache__/`, `*.py[cod]`) and all previously tracked
  `__pycache__`/`.pyc` artifacts removed from the index. No solver, model,
  validator or generator behavior changed.
- **P4 (complete)** — sequence-dependent setup / changeover: `changeover()`
  is the single source of truth shared by the CP-SAT model, the validator and
  the CLI setup summary. `generate_dataset(sequence_dependent_setup=True)`
  populates per-product `setup_family_id` plus a complete `setup_matrix`;
  without this data behaviour is unchanged (following operation's
  `setup_time`). Tests in `tests/test_sequence_dependent_setup.py`,
  `tests/test_generator_setup_families.py`, `tests/test_cli_setup_summary.py`.
- **P5 (complete)** — feasibility root-cause diagnostics:
  `analyze_infeasibility(ds, diagnostics=None)` is a post-solve layer that
  consumes the layered diagnostics and additional deterministic evidence
  (machine capacity, maintenance/downtime windows, minimum setup/changeover
  overhead) and ranks the detected causes into one root cause with
  deterministic severity order. Categories: MATERIAL_SHORTAGE,
  CAPACITY_SHORTAGE / MACHINE_CAPACITY, EMPLOYEE_SHORTAGE, CALENDAR_LIMITATION,
  MAINTENANCE_DOWNTIME, SETUP_CHANGEOVER_BURDEN, STRUCTURAL_INVALIDITY,
  UNKNOWN_INFEASIBILITY. The CLI prints `Root cause: <CAUSE>` plus concise
  details on infeasible runs; existing diagnostics output and exit codes are
  unchanged. Tests in `tests/test_feasibility_diagnostics.py`.

**Phase 7 — objective layer** (COMPLETE).

- **P1 (complete)** — objective extraction: the hardcoded weighted-tardiness
  objective is extracted from `ModelBuilder._objective()` into
  `aps_engine/objectives/` as a pluggable registry (`get_objective`,
  `registered_objectives`) with `weighted_tardiness` as the sole, default
  entry. `SolverParams.objective` (default `"weighted_tardiness"`) threads the
  selection through `ModelBuilder`. Behaviour is identical (material-feasible
  dataset still solves to OPTIMAL 39.0). Tests in
  `tests/test_objectives.py`.
- **P2 (complete)** — makespan objective: `aps_engine/objectives/makespan.py`
  minimizes `max(end_time over all operations)` via a `makespan` variable
  recorded on `builder.makespan_var`. Registered as `"makespan"`; weighted
  tardiness stays the default. Solving the material-feasible dataset with
  makespan is OPTIMAL (objective 1350.0), deterministic in objective value
  across repeated runs, and passes the independent validator. Tests in
  `tests/test_makespan.py`.
- **P3 (complete)** — CLI objective selection: `python -m aps_engine
  --objective <name>` validates the value against the registry and threads it
  through `SolverParams`. Invalid values fail cleanly (`ERROR: unknown
  objective '<name>' (valid: makespan, weighted_tardiness)`, exit 1) and a
  missing value reports `--objective requires a value`. All existing output,
  exit codes and defaults are unchanged. Tests in `tests/test_cli_objective.py`.
- **P4 (complete)** — documentation & housekeeping reconciliation: this file,
  `README.md` and `docs/ARCHITECTURE.md` updated to cover the Phase 7
  objective layer; test count and CLI verification recorded; all Phase 7 work
  committed. No solver, model, validator, generator or CLI behaviour changed.

**Phase 8 — productionization: persistence, service API, packaging**
(COMPLETE). Phase 8 converts the completed engine into a persistent,
service-ready core. It adds no scheduling intelligence: no new objectives,
constraints, algorithms or CLI output were introduced, and every Phase 1-7
behaviour (solver, model, validator, generator, CLI reports, exit codes,
banners) is unchanged. It explicitly does NOT add an HTTP/API server,
frontend/Gantt, database (persistence is JSON files only), multi-tenancy,
scenario/what-if, job queues or AI/Copilot.

- **P1 (complete)** — dataset JSON persistence: `aps_engine/io/dataset_io.py`
  serializes a `Dataset` to a versioned JSON document
  (`aps-engine.dataset.v1`) and rebuilds it losslessly
  (`dataset_to_json` / `dataset_from_json`). The round trip preserves the
  complete domain object graph including `meta`, materials/BOMs/inventory,
  calendars, employees/skills and the tuple-keyed `setup_matrix` (encoded as
  explicit `[from, to, minutes]` triples), so
  `generate_dataset(sequence_dependent_setup=True)` round-trips exactly.
  Reconstructed datasets are deep-equal to the original and solve to the
  same OPTIMAL values (39.0 weighted_tardiness, 1350.0 makespan). Tests in
  `tests/test_dataset_io.py`.
- **P2 (complete)** — result/schedule JSON persistence:
  `aps_engine/io/result_io.py` serializes a solve output document
  (`aps-engine.result.v1`) containing `SolveResult` (status, status code,
  objective value, best bound, conflicts, wall time) plus the schedule and
  diagnostics (which carry root-cause information when present). Status codes
  are stored as integers and restored to their `CpSolverStatus` enum so
  `SolveResult.optimal` keeps working. The raw CP-SAT `builder` is never
  serialized. API: `result_to_json` / `result_from_json` (string or parsed
  dict) plus `save_result` / `load_result` file helpers. Loaded schedules
  pass the independent validator. Tests in `tests/test_result_io.py`.
- **P3 (complete)** — service API facade: `aps_engine/api.py` exposes
  `plan(dataset_or_doc, objective="weighted_tardiness", params=None)` ->
  `ResultDocument`, a thin programmatic boundary that accepts a `Dataset` or
  the P1 dataset JSON document (string or parsed dict), validates the
  objective through the registry (unknown names raise the same `KeyError` as
  the CLI), runs the existing solve pipeline and returns a
  machine-consumable document in the exact P2 representation (`result` +
  `schedule`, including diagnostics/root-cause when present) — never the raw
  `ModelBuilder` / `CpModel` / `CpSolver` / `IntVar`. `plan` and
  `ResultDocument` are re-exported from `aps_engine/__init__.py`. Tests in
  `tests/test_api.py`.
- **P4 (complete)** — packaging & console entry point: `pyproject.toml`
  gained `[project.scripts]` with `aps-engine = "aps_engine.cli.main:main"`
  and a phase-neutral project description (runtime dependencies unchanged);
  `aps_engine/__init__.py` keeps `__version__`, `plan` and `ResultDocument`
  and gained a package docstring. Both `python -m aps_engine` and the
  installed `aps-engine` command were verified to preserve the existing CLI
  behaviour, output and exit codes. Tests in `tests/test_packaging.py`.
- **P5 (complete)** — documentation & reconciliation: this file, `README.md`
  and `docs/ARCHITECTURE.md` updated to cover the Phase 8 surface (IO layer,
  `plan` facade, `aps-engine` entry point); test count (369) and CLI /
  persistence / API verification recorded. No solver, model, validator,
  generator or CLI behaviour changed.

**Phase 9 — HTTP/Application API foundation** (COMPLETE). Phase 9 establishes
a thin, production-oriented FastAPI boundary around the completed engine. It
adds no scheduling intelligence and does NOT rewrite the APS Engine: routes
never contain solver/domain logic and never duplicate `plan()`. Architecture:
`Client -> FastAPI HTTP API -> application/service boundary ->
aps_engine.api.plan() -> APS Engine -> CP-SAT / Greedy / Validation /
Diagnostics`. The API application lives in its own `aps_api` package
(`pyproject.toml` now packages `aps_engine*` and `aps_api*`) and imports
cleanly without starting a server. Phase 9 explicitly does NOT provide
authentication, a database, multi-tenancy, a frontend/Gantt, async workers /
job queues, or a production deployment; those belong to future phases.

- **P1 (complete)** — HTTP API foundation: `aps_api/app.py` `create_app()`
  builds the FastAPI application (importable object `aps_api.app.app`).
  `GET /health` returns `{status, service}` liveness, and `GET /version`
  returns `{name, version}` where version comes from the single package
  version source via `importlib.metadata` (`aps_api/version.py`,
  `get_package_version`) — never manually duplicated. Runtime dependency
  `fastapi>=0.110` plus dev extras `httpx`, `uvicorn` added to
  `pyproject.toml`. Tests in `tests/test_api_http.py`.
- **P2 (complete)** — planning endpoint: `POST /plans` accepts a JSON dataset
  document in the Phase 8 persistence format and delegates to the Phase 8
  facade `aps_engine.api.plan()` through the application boundary
  (`aps_api/service.py` + `aps_api/routes/plans.py`). Default objective
  behaviour is unchanged; `weighted_tardiness` and `makespan` both work.
  Responses are JSON-serializable and ResultDocument-compatible
  (`{result, schedule}`); CP-SAT model objects, solver internals and
  non-serializable enums are never exposed.
- **P3 (complete)** — API contracts: explicit Pydantic schemas in
  `aps_api/schemas.py` for the planning request (`PlanningRequest` /
  `PlanningParams`), the planning response (`PlanningResponse`), the
  solve/result information (`ResultInfo`), the schedule (`Schedule`,
  `ScheduleOperation`, `ScheduleOrder`) and diagnostics (`Diagnostic`).
  Request validation happens *before* planner execution in the executor
  (`aps_api/executor.py`): invalid dataset documents and unknown objectives
  raise the domain `PlanningError` and never reach the solver. Invalid
  JSON / schema violations produce a deterministic 422 `VALIDATION_ERROR`;
  invalid domain payloads produce 400 (`INVALID_DATASET_DOCUMENT`,
  `UNKNOWN_OBJECTIVE`); unexpected internal failures produce a generic 500
  `INTERNAL_ERROR`. Every non-2xx response uses the single structured
  envelope `{"error": {"code", "message", "details"?}}`
  (`aps_api/errors.py`); no stack traces or internal implementation details
  leak.
- **P4 (complete)** — error & diagnostics contract: infeasible plans remain
  valid 200 responses with `schedule: null`, `result.status: INFEASIBLE` and
  the engine's layered diagnostics preserved verbatim (schedule `null` is
  never an HTTP 500). The HTTP layer only translates existing engine results
  into API-safe JSON rows (`code`, `order_id`, `operation_id`,
  `resource_type`, `resource_id`, `reason`) and does not redesign the
  diagnostic taxonomy (MATERIAL_SHORTAGE, EMPLOYEE_SHORTAGE,
  CAPACITY_SHORTAGE, CALENDAR_LIMITATION, MAINTENANCE_DOWNTIME,
  SETUP_CHANGEOVER_BURDEN, STRUCTURAL_INVALIDITY, UNKNOWN_INFEASIBILITY);
  `code` is a free-form string so new engine codes flow through unchanged.
- **P5 (complete)** — async-ready application boundary: `aps_api/executor.py`
  introduces a minimal `PlanExecutor` abstraction (`SyncPlanExecutor`
  today). `PlanningService` composes an injectable executor and
  `create_app(service=...)` accepts one, so a future phase can evolve
  `POST /plans` synchronous execution into job creation -> worker -> result
  retrieval (the worker runs the same executor payload contract) without
  rewriting the routes, the service boundary or the core engine. No
  Celery/Redis/broker/queue infrastructure is implemented.
- **P6 (complete)** — API integration tests: `tests/test_api_http.py`
  (TestClient against the real app, no external server/database) covers
  `/health`, `/version`, valid planning requests (default,
  `weighted_tardiness`, `makespan`, params override), invalid objective
  (400), malformed requests / schema violations (422), valid-but-infeasible
  datasets (200 + `schedule: null` + diagnostics), diagnostics/root-cause
  preservation (MATERIAL_SHORTAGE and EMPLOYEE_SHORTAGE fixtures), JSON
  serialization, no-solver-internal assertions and the structured error
  envelope; `tests/test_api_service.py` covers the service/executor/schema
  contracts directly (including executor injection and
  validation-before-solve). `tests/test_packaging.py` gained subprocess
  regressions proving `python -m aps_engine` and the installed `aps-engine`
  console entry point remain functional.
- **P7 (complete)** — documentation & reconciliation: this file and
  `README.md` updated with the Phase 9 surface (start the API locally,
  `/health`, `/version`, `POST /plans`, request/response behaviour,
  infeasibility semantics, example curl commands, test command); test count
  (410) recorded; all Phase 9 commits pushed. No solver, model, validator,
  generator or CLI behaviour changed.

## Next planned phase

None — Phases 1 through 9 (the documented roadmap, including the Phase 8
productionization: persistence, service API facade and packaging, and the
Phase 9 HTTP/Application API foundation) are fully implemented. Phase 9 is
the final planned phase; no further phase is planned in this repository yet.
