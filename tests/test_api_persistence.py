"""Phase 10 P5/P6 HTTP persistence integration tests.

Drive the real FastAPI application against a real PostgreSQL test database.
They verify the Phase 10 endpoints (``POST/GET /datasets`` and
``GET /plans``/``GET /plans/{id}``), that ``POST /plans`` persists a
``PlanningRun`` for feasible, infeasible and rejected requests, and that the
engine-only application (no database configured) is unchanged and exposes no
persistence endpoints. Skipped without PostgreSQL and the optional
``postgres`` dependencies.
"""

import json

import pytest
from fastapi.testclient import TestClient

from aps_engine.generator import generate_dataset, generate_infeasible_dataset
from aps_engine.io import dataset_to_json
from aps_persistence.database import Database

pytestmark = pytest.mark.usefixtures("migrated_database")

FEASIBLE_KW = {"material_feasible": True, "sequence_dependent_setup": True}


@pytest.fixture(scope="module")
def feasible_document():
    return json.loads(dataset_to_json(generate_dataset(**FEASIBLE_KW)))


@pytest.fixture(scope="module")
def infeasible_document():
    return json.loads(dataset_to_json(generate_infeasible_dataset()))


@pytest.fixture()
def database(migrated_database):
    db = Database.from_url(migrated_database)
    try:
        yield db
    finally:
        db.dispose()


@pytest.fixture()
def client(database):
    from aps_api.app import create_app

    return TestClient(create_app(database=database))


def test_create_list_and_get_dataset(client, feasible_document):
    created = client.post(
        "/datasets", json={"dataset": feasible_document, "name": "plant-a"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "plant-a"
    assert body["format"] == "aps-engine.dataset.v1"
    assert len(body["sha256"]) == 64
    assert body["document"]["orders"] == feasible_document["orders"]

    listed = client.get("/datasets")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]

    fetched = client.get(f"/datasets/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["meta"]["seed"] == feasible_document["meta"]["seed"]


def test_create_dataset_invalid_document_400(client):
    response = client.post("/datasets", json={"dataset": {"format": "v0"}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATASET_DOCUMENT"


def test_get_unknown_dataset_404(client):
    response = client.get("/datasets/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DATASET_NOT_FOUND"


def test_post_plan_persists_feasible_run(client, feasible_document):
    response = client.post("/plans", json={"dataset": feasible_document})
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "OPTIMAL"

    history = client.get("/plans")
    assert history.status_code == 200
    runs = history.json()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["outcome"] == "optimal"
    assert run["feasible"] is True
    assert run["dataset_id"]

    detail = client.get(f"/plans/{run['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["result"]["status"] == "OPTIMAL"
    assert body["result"]["objective_value"] == 39.0
    assert body["schedule"] is not None
    assert body["error_code"] is None


def test_post_plan_infeasible_is_completed_not_error(client, infeasible_document):
    response = client.post("/plans", json={"dataset": infeasible_document})
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "INFEASIBLE"
    assert response.json()["schedule"] is None

    run = client.get("/plans").json()[0]
    assert run["status"] == "completed"
    assert run["outcome"] == "infeasible"
    assert run["feasible"] is False
    detail = client.get(f"/plans/{run['id']}").json()
    assert detail["schedule"] is None
    assert len(detail["diagnostics"]) > 0


def test_post_plan_rejected_request_is_recorded(client, feasible_document):
    response = client.post(
        "/plans", json={"dataset": feasible_document, "objective": "nope"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_OBJECTIVE"

    runs = client.get("/plans").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["outcome"] == "invalid_request"
    detail = client.get(f"/plans/{runs[0]['id']}").json()
    assert detail["error_code"] == "UNKNOWN_OBJECTIVE"


def test_post_plan_by_dataset_id(client, feasible_document):
    ds_id = client.post("/datasets", json={"dataset": feasible_document}).json()["id"]
    response = client.post(
        "/plans", json={"dataset": feasible_document, "dataset_id": ds_id}
    )
    assert response.status_code == 200

    runs = client.get("/plans", params={"dataset_id": ds_id}).json()
    assert len(runs) == 1
    assert runs[0]["dataset_id"] == ds_id
    assert client.get("/plans", params={"dataset_id": "other"}).json() == []


def test_post_plan_unknown_dataset_id_404(client, feasible_document):
    response = client.post(
        "/plans", json={"dataset": feasible_document, "dataset_id": "missing"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DATASET_NOT_FOUND"


def test_get_unknown_plan_404(client):
    response = client.get("/plans/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAN_NOT_FOUND"


def test_persistent_plan_links_dataset_by_content(client, feasible_document):
    client.post("/plans", json={"dataset": feasible_document})
    client.post("/plans", json={"dataset": feasible_document})

    datasets = client.get("/datasets").json()
    runs = client.get("/plans").json()
    assert len(datasets) == 1
    assert len(runs) == 2
    assert {run["dataset_id"] for run in runs} == {datasets[0]["id"]}


def test_engine_only_app_has_no_persistence_endpoints():
    from aps_api import app as engine_only_app

    engine_client = TestClient(engine_only_app)
    assert engine_client.get("/datasets").status_code == 404
    # POST /plans exists, so GET /plans is method-not-allowed rather than 404.
    assert engine_client.get("/plans").status_code == 405
