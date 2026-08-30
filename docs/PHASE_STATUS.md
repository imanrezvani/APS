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
| Phase 6 P4 — sequence-dependent setup / changeover | COMPLETE |
| Phase 6 P5 — feasibility root-cause diagnostics | COMPLETE |

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

## Tests / status

- Full suite: **298 passed, 0 failed, 0 skipped** (`python -m pytest`).
- Coverage: generator 9, validator 24, solver 20, setup 9, diagnostics 10,
  pre-solve 17, CLI E2E 2, sequence-dependent setup 24, material + BOM 13,
  inventory 11, BOM integration 17, material requirements 20,
  material feasibility 10, production-order material feasibility 7,
  order-book material feasibility 8, pre-solve materials 10, material demand 9,
  material-feasible scenario 8, CLI material report 5, generator setup
  families 5, greedy 15, benchmark 7, CLI setup summary 2, feasibility
  diagnostics 16, validator material 6.
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

## Next planned phase

None — the documented roadmap is fully implemented. Any future phase is
not planned in this repository yet.
