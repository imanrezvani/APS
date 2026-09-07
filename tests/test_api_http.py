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
