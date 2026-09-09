"""Phase 9 P3 service-boundary and schema-contract unit tests.

Direct unit tests of the application boundary (``aps_api.service``) and the
Pydantic contracts (``aps_api.schemas``) that the HTTP integration tests in
``test_api_http.py`` exercise end-to-end. These verify the boundary
guarantees without an HTTP server: planning payloads are ResultDocument
compatible (feasible 200-like payload / infeasible with diagnostics), domain
validation happens before any planner call and raises ``PlanningError``, the
default solver params mirror the engine, and the schemas reject unknown
fields and out-of-range settings deterministically.
"""

import json

import pytest
from pydantic import ValidationError

from aps_api.errors import PlanningError
from aps_api.schemas import PlanningRequest, PlanningResponse
from aps_api.service import PlanningService

from aps_engine.generator import generate_dataset, generate_infeasible_dataset
from aps_engine.io.dataset_io import dataset_to_json
from aps_engine.solver.model import SolverParams


@pytest.fixture(scope="module")
def material_document():
    dataset = generate_dataset(material_feasible=True, sequence_dependent_setup=True)
    return json.loads(dataset_to_json(dataset))


@pytest.fixture(scope="module")
def infeasible_document():
    return json.loads(dataset_to_json(generate_infeasible_dataset()))


@pytest.fixture()
def service():
    return PlanningService()


# ------------------------------------------------------------ service boundary

def test_service_valid_plan_payload_shape(service, material_document):
    payload = service.create_plan({"dataset": material_document})
    assert set(payload) == {"result", "schedule"}
    assert payload["result"]["feasible"] is True
    assert payload["schedule"] is not None
    assert payload["result"]["status"] == "OPTIMAL"
    assert payload["result"]["objective_value"] > 0
    assert payload["schedule"]["operations"]
    assert payload["schedule"]["orders"]


def test_service_makespan_objective(service, material_document):
    payload = service.create_plan(
        {"dataset": material_document, "objective": "makespan"}
    )
    assert payload["result"]["feasible"] is True
    assert payload["schedule"]["objective_value"] == payload["result"]["objective_value"]


def test_service_infeasible_is_result_not_error(service, infeasible_document):
    payload = service.create_plan({"dataset": infeasible_document})
    assert payload["result"]["feasible"] is False
    assert payload["result"]["status"] == "INFEASIBLE"
    assert payload["schedule"] is None
    assert len(payload["result"]["diagnostics"]) > 0


def test_service_unknown_objective_raises_planning_error(service, material_document):
    with pytest.raises(PlanningError) as err:
        service.create_plan({"dataset": material_document, "objective": "bogus"})
    assert err.value.code == "UNKNOWN_OBJECTIVE"
    assert "weighted_tardiness" in err.value.message
    assert "makespan" in err.value.message


def test_service_invalid_dataset_document_raises_planning_error(service):
    with pytest.raises(PlanningError) as err:
        service.create_plan({"dataset": {"format": "v0"}, "objective": "makespan"})
    assert err.value.code == "INVALID_DATASET_DOCUMENT"


def test_service_validation_happens_before_solve(monkeypatch, material_document):
    """Rejected inputs must never reach the planner."""
    calls = []

    def fake_plan(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("planner must not run for an invalid objective")

    monkeypatch.setattr("aps_api.service.plan", fake_plan)
    with pytest.raises(PlanningError):
        service = PlanningService()
        service.create_plan({"dataset": material_document, "objective": "nope"})
    assert calls == []


def test_service_default_solver_params_match_engine():
    from aps_api.service import _solver_params

    params = _solver_params("makespan", None)
    assert isinstance(params, SolverParams)
    assert params.objective == "makespan"
    assert params.time_limit_seconds == 30
    assert params.num_search_workers == 2
    assert params.random_seed == 42


def test_service_solver_params_overrides():
    from aps_api.service import _solver_params

    params = _solver_params(
        "weighted_tardiness", {"time_limit_seconds": 7, "random_seed": 9}
    )
    assert params.time_limit_seconds == 7
    assert params.num_search_workers == 2
    assert params.random_seed == 9


# -------------------------------------------------------------------- schemas

def test_schema_request_defaults(material_document):
    request = PlanningRequest.model_validate({"dataset": material_document})
    assert request.objective == "weighted_tardiness"
    assert request.params is None


def test_schema_request_rejects_extra_field(material_document):
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate(
            {"dataset": material_document, "objective": "makespan", "oops": 1}
        )


def test_schema_request_rejects_out_of_range_params(material_document):
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate(
            {"dataset": material_document, "params": {"time_limit_seconds": 0}}
        )
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate(
            {"dataset": material_document, "params": {"num_search_workers": 64}}
        )


def test_schema_response_round_trip(service, material_document):
    document = service.create_plan({"dataset": material_document})
    response = PlanningResponse.model_validate(document)
    assert response.result.feasible is True
    assert response.schedule is not None
    assert response.schedule.objective_value == response.result.objective_value
    assert response.model_dump(mode="json") == document
