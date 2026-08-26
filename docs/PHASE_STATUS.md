# Phase Status

| Phase | Status |
| --- | --- |
| Phase 1 — baseline model (machines, precedence, objective) | COMPLETE |
| Phase 2 — factory calendar (shifts, holidays, maintenance, downtime) | COMPLETE |
| Phase 3 — employee assignment (skills, work centers, shifts, availability) | COMPLETE |
| Sequence-dependent setup gap fix (pairwise changeover gating) | COMPLETE |
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

## Current state

- Uniform pairwise disjunctive capacity model in `aps_engine/solver/model.py`:
  `NoOverlap` on plain processing intervals + per-pair ordering literals
  whose changeover gaps come from `changeover()`.
- Setup-pair constraints are gated on machine assignment (`on_im` of both
  involved operations), so a changeover on an unselected candidate machine
  does not constrain an operation scheduled on another compatible machine.
- Setup on a shared machine still binds; op->op changeover and post-maintenance
  setup act as independent lower bounds (never summed).
- No setup family / setup matrix data reproduces the previous
  sequence-independent behavior exactly.

## Tests / status

- Full suite: **228 passed, 0 failed, 0 skipped** (`python -m pytest`).
- Coverage: generator 9, validator 24, solver 20, setup 9, diagnostics 10,
  pre-solve 17, CLI E2E 2, sequence-dependent setup 19, material + BOM 13,
  inventory 11, BOM integration 17, material requirements + availability 20,
  material feasibility 10, production-order material feasibility 7,
  order-book material feasibility 8, pre-solve materials 10, material demand 9,
  material-feasible scenario 8, CLI material report 5.
- Regression: `test_operation_assigned_elsewhere_not_constrained_by_candidate_pair`
  proves an op assigned to another machine is not constrained by an unselected
  machine's changeover (PANEL->FLAT = 100000, both ops still start at 480).
- CLI (`python -m aps_engine`): exit 0, `STATUS: OPTIMAL`, objective 39.0,
  best bound 39.0, `valid: True violations: 0`, `Employee violations: 0`,
  26 changeovers / 370 setup minutes.
- Infeasible E2E (`--infeasible`): exit 1, `EMPLOYEE_SHORTAGE`.

## Next planned phase

**Phase 4 — Materials + Inventory** (COMPLETE). Phase 4.7 delivered the
material-demand interface (`material_demand(order_id)`, `material_demands()`),
a deterministic material-feasible dataset scenario
(`generate_dataset(material_feasible=True)`), and a read-only CLI material
feasibility report (`[8] MATERIAL FEASIBILITY`, plus `--material-feasible`).
Default dataset stays material-infeasible; both variants solve to OPTIMAL 39.0,
valid, 0 violations; CLI exit codes unchanged.

**Phase 5 — APS Solver**: material constraints inside the CP-SAT model,
implemented through the standard staged workflow (implement stage -> test ->
report -> gate approval).

- **P1 (complete)** — aggregate material availability as a hard constraint plus a
  `MATERIAL_SHORTAGE` diagnostics layer: when the aggregate order-book demand
  of a material exceeds on-hand inventory the model is INFEASIBLE and the
  diagnostics report one MATERIAL_SHORTAGE per short material. Default dataset
  (material-short) is INFEASIBLE; `material_feasible=True` still solves to
  OPTIMAL 39.0. Tests in `tests/test_material_solver.py`.
- **P2 (complete)** — time-phased material consumption: each material's on-hand
  inventory is a cumulative capacity that orders draw on for the whole duration
  of their production chain (start of first operation to end of last). An order
  commits its full BOM demand from chain start to chain end and the committed
  working stock never exceeds on-hand at any instant, so orders sharing a
  scarce material interact in time (they are serialized when stock is tight).
  Demand and capacity are scaled x100 to keep fractional BOM quantities exact.
  Consumption happens only inside the solver model; the Dataset is never
  mutated. Default dataset stays INFEASIBLE and `material_feasible=True` still
  solves to OPTIMAL 39.0. Tests in `tests/test_material_consumption.py`.
- **P3 (complete)** — independent material validation + CLI/docs: the
  validator (`validation/validator.py`) re-derives time-phased material
  consumption from the schedule and BOMs alone (never inspecting CP-SAT):
  each order commits its BOM demand for its whole production chain and the
  peak committed working stock per material must not exceed on-hand,
  reported as `MATERIAL_VIOLATION` with material_id / required / available /
  shortage details. CLI `[7] VALIDATION` prints a `material
  (MATERIAL_VIOLATION): N` line; the feasible variant stays
  `valid: True`, 0 violations and the default material-short dataset stays
  INFEASIBLE with MATERIAL_SHORTAGE diagnostics (exit codes unchanged). Tests
  in `tests/test_validator_material.py` (validator fixture switched to the
  material-feasible variant so the constructive-schedule tests stay
  material-valid). Full suite: **248 passed, 0 failed**.
