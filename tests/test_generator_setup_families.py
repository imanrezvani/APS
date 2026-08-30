"""Phase 6 P4 generator setup-family tests.

TEST 1: the default dataset stays sequence-independent (empty families and
        matrix).
TEST 2: ``sequence_dependent_setup=True`` populates ``setup_family_id`` (per
        product) and the global ``setup_matrix``.
TEST 3: the family dataset is deterministic.
TEST 4: a family-enabled, material-feasible dataset solves and validates with
        both the CP-SAT solver and the greedy scheduler.
TEST 5: the sequence-dependent flag is independent of ``material_feasible``
        (default inventory untouched).
"""

from aps_engine.generator import SETUP_FAMILIES, generate_dataset
from aps_engine.solver.greedy import greedy_solve
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate


def test_default_dataset_has_no_setup_families():
    ds = generate_dataset()
    assert ds.meta["sequence_dependent_setup"] is False
    assert ds.setup_matrix == {}
    assert all(op.setup_family_id == "" for op in ds.operations.values())


def test_family_dataset_populates_families_and_matrix():
    ds = generate_dataset(sequence_dependent_setup=True)
    assert ds.meta["sequence_dependent_setup"] is True
    assert len(ds.setup_matrix) == len(SETUP_FAMILIES) ** 2
    assert all(op.setup_family_id != "" for op in ds.operations.values())
    for order in ds.orders.values():
        expected = SETUP_FAMILIES[order.product_id]
        for op_id in ds.routings[order.id].operations:
            assert ds.operations[op_id].setup_family_id == expected


def test_family_dataset_deterministic():
    a = generate_dataset(sequence_dependent_setup=True)
    b = generate_dataset(sequence_dependent_setup=True)
    assert a.setup_matrix == b.setup_matrix
    assert {o.setup_family_id for o in a.operations.values()} \
        == {o.setup_family_id for o in b.operations.values()}


def test_family_dataset_solves_and_validates():
    ds = generate_dataset(sequence_dependent_setup=True, material_feasible=True)
    cp = solve(ds, SolverParams())
    assert cp["result"].feasible
    assert validate(ds, cp["schedule"]).valid
    gr = greedy_solve(ds)
    assert gr["result"].feasible
    assert validate(ds, gr["schedule"]).valid


def test_family_flag_independent_of_material_flag():
    ds = generate_dataset(sequence_dependent_setup=True)
    assert ds.setup_matrix
    assert ds.meta["material_feasible"] is False
    assert ds.inventory["M_HINGE"].on_hand == 30
