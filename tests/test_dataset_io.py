"""Phase 8 P1 dataset JSON persistence tests.

Verifies the ``aps_engine.io`` lossless Dataset round trip across the three
dataset variants (default, material-feasible, sequence-dependent-setup and
their combination), that the reconstructed Dataset is deep-equal to the
original (including the tuple-keyed ``setup_matrix``), that the JSON text
survives a real file persist/load cycle, and that solving the reconstructed
dataset reproduces the original solve exactly (weighted_tardiness OPTIMAL
39.0, makespan OPTIMAL 1350.0).
"""

import json

import pytest

from aps_engine.generator import generate_dataset
from aps_engine.io.dataset_io import FORMAT, dataset_from_json, dataset_to_json
from aps_engine.solver.model import SolverParams
from aps_engine.solver.solver import solve
from aps_engine.validation.validator import validate

DATASET_VARIANTS = [
    pytest.param({}, id="default"),
    pytest.param({"material_feasible": True}, id="material-feasible"),
    pytest.param({"sequence_dependent_setup": True}, id="sequence-dependent"),
    pytest.param(
        {"material_feasible": True, "sequence_dependent_setup": True},
        id="material-feasible-sequence-dependent",
    ),
]


@pytest.fixture(params=DATASET_VARIANTS)
def dataset(request):
    return generate_dataset(**request.param)


def test_roundtrip_deep_equal(dataset):
    restored = dataset_from_json(dataset_to_json(dataset))
    assert restored == dataset
    assert restored.meta == dataset.meta
    assert restored.setup_matrix == dataset.setup_matrix
    assert list(restored.operations) == list(dataset.operations)


def test_roundtrip_survives_file_persist_cycle(dataset, tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(dataset_to_json(dataset))
    restored = dataset_from_json(path.read_text())
    assert restored == dataset


def test_to_json_produces_valid_json_text(dataset):
    parsed = json.loads(dataset_to_json(dataset))
    assert parsed["format"] == FORMAT


def test_from_json_accepts_parsed_document(dataset):
    document = json.loads(dataset_to_json(dataset))
    assert dataset_from_json(document) == dataset


def test_setup_matrix_tuple_keys_roundtrip():
    ds = generate_dataset(sequence_dependent_setup=True)
    assert ds.setup_matrix
    restored = dataset_from_json(dataset_to_json(ds))
    key = next(iter(ds.setup_matrix))
    assert isinstance(key, tuple)
    assert restored.setup_matrix == ds.setup_matrix
    for (from_family, to_family), minutes in restored.setup_matrix.items():
        assert isinstance(from_family, str)
        assert isinstance(to_family, str)
        assert isinstance(minutes, int)


def test_format_mismatch_rejected():
    with pytest.raises(ValueError):
        dataset_from_json({"format": "aps-engine.dataset.v0"})


@pytest.mark.parametrize("objective,expected", [
    ("weighted_tardiness", 39.0),
    ("makespan", 1350.0),
], ids=["weighted-tardiness", "makespan"])
def test_solve_parity_original_vs_loaded(objective, expected):
    ds = generate_dataset(material_feasible=True, sequence_dependent_setup=True)
    restored = dataset_from_json(dataset_to_json(ds))
    params = SolverParams(
        objective=objective, time_limit_seconds=30,
        num_search_workers=2, random_seed=42)
    original = solve(ds, params)
    loaded = solve(restored, params)

    assert loaded["result"].feasible, loaded["result"].status
    assert loaded["result"].optimal, loaded["result"].status
    assert loaded["result"].objective_value == expected
    assert loaded["result"].objective_value == original["result"].objective_value
    assert validate(restored, loaded["schedule"]).valid
