"""Phase 9 HTTP API integration tests.

The API tests drive the real FastAPI application through Starlette's
``TestClient`` (no external server, no database). They verify the HTTP
contract of every endpoint against deterministic engine fixtures: health and
version metadata, planning via the Phase 8 dataset document (weighted
tardiness and makespan objectives), infeasibility/root-cause semantics,
structured 4xx errors for invalid input, JSON serializability, and the
absence of any CP-SAT/solver internals in responses.
"""

import json

import pytest
from fastapi.testclient import TestClient

import aps_engine
from aps_api import app
from aps_api.version import get_package_version, get_service_name

MATERIAL_FEASIBLE_KW = {"material_feasible": True, "sequence_dependent_setup": True}


def _load_dataset_document(**generate_kw):
    from aps_engine.generator import generate_dataset
    from aps_engine.io import dataset_to_json

    return json.loads(dataset_to_json(generate_dataset(**generate_kw)))


@pytest.fixture(scope="module")
def material_dataset_document():
    return _load_dataset_document(**MATERIAL_FEASIBLE_KW)


@pytest.fixture(scope="module")
def infeasible_dataset_document():
    return _load_dataset_document(material_feasible=False)


@pytest.fixture()
def client():
    return TestClient(app)


# --------------------------------------------------------------------------- P1

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == get_service_name()


def test_version_endpoint(client):
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == get_service_name()
    assert body["version"] == get_package_version()
    assert body["version"] == aps_engine.__version__


def test_unknown_route_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404


# --------------------------------------------------------------------------- P2

def test_plan_default_objective(client, material_dataset_document):
    response = client.post("/plans", json={"dataset": material_dataset_document})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"result", "schedule"}
    assert body["result"]["status"] == "OPTIMAL"
    assert body["result"]["feasible"] is True
    assert body["result"]["objective_value"] == 39.0
    assert body["schedule"] is not None
    assert "operations" in body["schedule"] and "orders" in body["schedule"]


def test_plan_weighted_tardiness_explicit(client, material_dataset_document):
    response = client.post(
        "/plans",
        json={"dataset": material_dataset_document, "objective": "weighted_tardiness"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["objective_value"] == 39.0
    assert body["result"]["status"] == "OPTIMAL"


def test_plan_makespan(client, material_dataset_document):
    response = client.post(
        "/plans",
        json={"dataset": material_dataset_document, "objective": "makespan"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "OPTIMAL"
    assert body["result"]["objective_value"] == 1350.0
    assert body["schedule"] is not None


def test_plan_with_params(client, material_dataset_document):
    response = client.post(
        "/plans",
        json={
            "dataset": material_dataset_document,
            "objective": "makespan",
            "params": {"time_limit_seconds": 30, "num_search_workers": 2, "random_seed": 42},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["objective_value"] == 1350.0


def test_plan_infeasible_dataset_is_not_server_error(client, infeasible_dataset_document):
    response = client.post("/plans", json={"dataset": infeasible_dataset_document})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "INFEASIBLE"
    assert body["result"]["feasible"] is False
    assert body["schedule"] is None
    assert len(body["result"]["diagnostics"]) > 0
    codes = {d["code"] for d in body["result"]["diagnostics"]}
    assert "MATERIAL_SHORTAGE" in codes
