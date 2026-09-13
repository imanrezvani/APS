"""PlanningRun repository tests (Phase 10 P4).

Require a real PostgreSQL test database; skipped otherwise. Payloads are
produced by the real Phase 8 pipeline (``aps_engine.api.plan`` +
``result_io``) so the repository is exercised against authentic JSON-safe
result documents for feasible, infeasible and rejected runs.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aps_engine.api import plan
from aps_engine.generator.generator import generate_dataset, generate_infeasible_dataset
from aps_engine.io.result_io import result_to_json
from aps_persistence import models
from aps_persistence.repositories import (
    DatasetRepository,
    PlanningRunNotFoundError,
    PlanningRunRepository,
)

pytestmark = pytest.mark.usefixtures("migrated_database")


@pytest.fixture(scope="module")
def feasible_dataset():
    return generate_dataset(material_feasible=True, sequence_dependent_setup=True)


@pytest.fixture(scope="module")
def feasible_payload(feasible_dataset):
    return _payload(feasible_dataset)


@pytest.fixture()
def session(migrated_database):
    engine = create_engine(migrated_database, future=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _payload(dataset, objective="weighted_tardiness"):
    document = plan(dataset, objective=objective)
    parsed = json.loads(result_to_json(document))
    return {"result": parsed["result"], "schedule": parsed["schedule"]}


def test_complete_feasible_run(session, feasible_dataset, feasible_payload):
    ds_record = DatasetRepository(session).create(feasible_dataset)
    session.commit()

    repo = PlanningRunRepository(session)
    run = repo.start(dataset_id=ds_record.id, objective="weighted_tardiness")
    assert run.status == models.RUN_RUNNING
    assert run.started_at is not None

    repo.complete(run, feasible_payload)
    session.commit()

    assert run.status == models.RUN_COMPLETED
    assert run.outcome in (models.OUTCOME_OPTIMAL, models.OUTCOME_FEASIBLE)
    assert run.feasible is True
    assert run.result_status in ("OPTIMAL", "FEASIBLE")
    assert run.schedule is not None
    assert isinstance(run.diagnostics, list)

    loaded = repo.load_result(run.id)
    assert loaded["result"].feasible is True
    assert loaded["schedule"] == run.schedule


def test_complete_infeasible_run_is_not_failure(session):
    dataset = generate_infeasible_dataset()
    ds_record = DatasetRepository(session).create(dataset)
    session.commit()

    repo = PlanningRunRepository(session)
    run = repo.start(dataset_id=ds_record.id, objective="weighted_tardiness")
    repo.complete(run, _payload(dataset))
    session.commit()

    assert run.status == models.RUN_COMPLETED
    assert run.outcome == models.OUTCOME_INFEASIBLE
    assert run.feasible is False
    assert run.schedule is None

    loaded = repo.load_result(run.id)
    assert loaded["result"].feasible is False
    assert loaded["schedule"] is None


def test_fail_invalid_request_classified(session):
    repo = PlanningRunRepository(session)
    run = repo.start(dataset_id=None, objective="weighted_tardiness")
    repo.fail(
        run,
        error_code="INVALID_DATASET_DOCUMENT",
        error_message="bad document",
    )
    session.commit()

    assert run.status == models.RUN_FAILED
    assert run.outcome == models.OUTCOME_INVALID_REQUEST
    assert run.error_code == "INVALID_DATASET_DOCUMENT"
    assert run.completed_at is not None
    with pytest.raises(ValueError):
        repo.load_result(run.id)


def test_fail_execution_error_classified(session):
    repo = PlanningRunRepository(session)
    run = repo.create_pending(dataset_id=None, objective="weighted_tardiness")
    assert run.status == models.RUN_PENDING
    repo.fail(run, error_code="EXECUTION_ERROR", error_message="boom")
    session.commit()
    assert run.outcome == models.OUTCOME_EXECUTION_FAILURE


def test_objective_params_and_dataset_link_persisted(
    session, feasible_dataset, feasible_payload
):
    ds_record = DatasetRepository(session).create(feasible_dataset)
    session.commit()

    repo = PlanningRunRepository(session)
    run = repo.start(
        dataset_id=ds_record.id,
        objective="weighted_tardiness",
        params={"time_limit_seconds": 10, "num_search_workers": 1, "random_seed": 7},
    )
    repo.complete(run, feasible_payload)
    session.commit()

    stored = repo.require(run.id)
    assert stored.objective == "weighted_tardiness"
    assert stored.params["random_seed"] == 7
    assert stored.dataset_id == ds_record.id
    assert repo.dataset_record(stored).id == ds_record.id


def test_list_records_scoped_by_dataset(session):
    dataset = generate_dataset(n_orders=2, seed=11)
    ds_record = DatasetRepository(session).create(dataset)
    session.commit()

    repo = PlanningRunRepository(session)
    first = repo.start(dataset_id=ds_record.id, objective="weighted_tardiness")
    second = repo.start(dataset_id=ds_record.id, objective="weighted_tardiness")
    other = repo.start(dataset_id=None, objective="weighted_tardiness")
    repo.fail(other, error_code="EXECUTION_ERROR", error_message="x")
    session.commit()

    scoped = {r.id for r in repo.list_records(dataset_id=ds_record.id)}
    assert scoped == {first.id, second.id}
    assert {r.id for r in repo.list_records()} >= {first.id, second.id, other.id}


def test_require_and_load_result_raise_for_unknown(session):
    repo = PlanningRunRepository(session)
    with pytest.raises(PlanningRunNotFoundError):
        repo.require("missing")
    with pytest.raises(PlanningRunNotFoundError):
        repo.load_result("missing")
