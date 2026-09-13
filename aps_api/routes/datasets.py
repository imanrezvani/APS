"""Dataset route handlers (Phase 10 P5).

Thin HTTP boundary over ``aps_api.service.DatasetService``: create, list and
fetch datasets. All validation and SQL live in the application service and
the persistence repositories; no engine or database code is imported here.
"""

from typing import List, Optional

from fastapi import APIRouter, Request

from aps_api.schemas import DatasetCreateRequest, DatasetDetail, DatasetSummary
from aps_api.service import DatasetService

router = APIRouter(tags=["datasets"])


def _service(http_request: Request) -> DatasetService:
    service: Optional[DatasetService] = getattr(
        http_request.app.state, "dataset_service", None
    )
    if service is None:
        raise RuntimeError("dataset service is not configured on the application")
    return service


@router.post(
    "/datasets",
    status_code=201,
    response_model=DatasetDetail,
    summary="Persist a dataset",
    description="Store a Phase 8 dataset document and its relational projection.",
)
def create_dataset(
    payload: DatasetCreateRequest, http_request: Request
) -> DatasetDetail:
    return DatasetDetail.model_validate(
        _service(http_request).create_dataset(payload.model_dump())
    )


@router.get(
    "/datasets",
    response_model=List[DatasetSummary],
    summary="List persisted datasets",
)
def list_datasets(http_request: Request) -> List[DatasetSummary]:
    return [
        DatasetSummary.model_validate(record)
        for record in _service(http_request).list_datasets()
    ]


@router.get(
    "/datasets/{dataset_id}",
    response_model=DatasetDetail,
    summary="Get a persisted dataset",
)
def get_dataset(dataset_id: str, http_request: Request) -> DatasetDetail:
    return DatasetDetail.model_validate(
        _service(http_request).get_dataset(dataset_id)
    )
