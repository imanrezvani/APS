"""Planning and dataset application services (Phase 9, extended in Phase 10).

The route layer never touches the engine or SQL. ``PlanningService`` is the
single application-boundary entry point for planning; ``DatasetService`` owns
dataset create/read orchestration. Both delegate execution/validation to
injectable components (:class:`aps_api.executor.PlanExecutor`) and, when a
``Database`` is configured, to the Phase 10 persistence repositories.

Phase 9 behavior is preserved exactly when no database is configured: the
synchronous executor runs and no persistence/SQL is involved. PostgreSQL is
only imported lazily (inside the persistence methods), so engine-only/CLI
workflows keep running without the optional ``postgres`` dependencies.
"""

from typing import Any, Dict, Optional

from aps_api.errors import NotFoundError, PlanningError
from aps_api.executor import PlanExecutor, SyncPlanExecutor


class DatasetService:
    """Create/read datasets against the Phase 10 persistence layer."""

    def __init__(self, database: Any) -> None:
        self._database = database

    @property
    def database(self) -> Any:
        return self._database

    @staticmethod
    def _validate(dataset_document: Any) -> Any:
        from aps_engine.io.dataset_io import dataset_from_json

        try:
            return dataset_from_json(dataset_document)
        except (TypeError, ValueError) as exc:
            raise PlanningError(
                "INVALID_DATASET_DOCUMENT",
                f"dataset is not a valid Phase 8 dataset document: {exc}",
            ) from exc

    @staticmethod
    def _summary(record: Any) -> Dict[str, Any]:
        return {
            "id": record.id,
            "name": record.name,
            "format": record.format,
            "sha256": record.sha256,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @classmethod
    def _detail(cls, record: Any) -> Dict[str, Any]:
        detail = cls._summary(record)
        detail["meta"] = record.meta
        detail["document"] = record.doc
        return detail

    def create_dataset(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from aps_persistence.repositories import DatasetRepository

        dataset = self._validate(request.get("dataset"))
        with self._database.session() as session:
            record = DatasetRepository(session).create(
                dataset,
                name=request.get("name"),
                extra_meta=request.get("meta"),
            )
            return self._detail(record)

    def list_datasets(self) -> list:
        from aps_persistence.repositories import DatasetRepository

        with self._database.session() as session:
            return [self._summary(r) for r in DatasetRepository(session).list_records()]

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        from aps_persistence.repositories import (
            DatasetNotFoundError,
            DatasetRepository,
        )

        with self._database.session() as session:
            try:
                record = DatasetRepository(session).require_record(dataset_id)
            except DatasetNotFoundError as exc:
                raise NotFoundError(
                    "DATASET_NOT_FOUND", f"dataset {dataset_id!r} was not found"
                ) from exc
            return self._detail(record)


class PlanningService:
    """Application boundary over a :class:`PlanExecutor` (and persistence).

    ``executor`` is injectable so tests and a future async phase can
    substitute a job-backed implementation without touching the routes.
    ``database`` is optional; when supplied, planning results and their
    lifecycle are persisted and run history becomes queryable.
    """

    def __init__(
        self,
        executor: Optional[PlanExecutor] = None,
        database: Any = None,
    ) -> None:
        self._executor = executor if executor is not None else SyncPlanExecutor()
        self._database = database

    @property
    def executor(self) -> PlanExecutor:
        return self._executor

    @property
    def database(self) -> Any:
        return self._database

    @property
    def has_persistence(self) -> bool:
        return self._database is not None

    # -- planning -------------------------------------------------------

    def create_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and run a planning request; return the JSON-safe payload.

        Without a database this is the Phase 9 synchronous path. With a
        database the dataset is loaded (``dataset_id``) or created
        (``dataset`` document), a ``PlanningRun`` is opened, the result is
        persisted and the same payload is returned. An infeasible plan is a
        successful run, never an error.
        """
        if self._database is None:
            return self._executor.execute(request)
        return self._create_persistent_plan(request)

    def _create_persistent_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from aps_engine.io.dataset_io import dataset_from_json
        from aps_persistence.repositories import (
            DatasetNotFoundError,
            DatasetRepository,
            PlanningRunRepository,
        )

        objective = request.get("objective", "weighted_tardiness")
        params = request.get("params") or {}
        dataset_id = request.get("dataset_id")

        with self._database.session() as session:
            datasets = DatasetRepository(session)
            runs = PlanningRunRepository(session)
            run = None
            try:
                if dataset_id:
                    record = datasets.require_record(dataset_id)
                else:
                    dataset = dataset_from_json(request.get("dataset"))
                    record = datasets.find_or_create(dataset)

                run = runs.start(
                    dataset_id=record.id, objective=objective, params=params
                )
                payload = self._executor.execute(
                    {
                        "dataset": record.doc,
                        "objective": objective,
                        "params": params,
                    }
                )
                runs.complete(run, payload)
                return payload
            except DatasetNotFoundError as exc:
                run = run or runs.start(
                    dataset_id=None, objective=objective, params=params
                )
                runs.fail(run, error_code="DATASET_NOT_FOUND", error_message=str(exc))
                session.commit()
                raise NotFoundError(
                    "DATASET_NOT_FOUND", f"dataset {dataset_id!r} was not found"
                ) from exc
            except (TypeError, ValueError) as exc:
                run = run or runs.start(
                    dataset_id=None, objective=objective, params=params
                )
                runs.fail(
                    run,
                    error_code="INVALID_DATASET_DOCUMENT",
                    error_message=str(exc),
                )
                session.commit()
                raise PlanningError(
                    "INVALID_DATASET_DOCUMENT",
                    f"dataset is not a valid Phase 8 dataset document: {exc}",
                ) from exc
            except PlanningError as exc:
                run = run or runs.start(
                    dataset_id=None, objective=objective, params=params
                )
                runs.fail(run, error_code=exc.code, error_message=exc.message)
                session.commit()
                raise

    # -- run history ----------------------------------------------------

    @staticmethod
    def _run_summary(record: Any) -> Dict[str, Any]:
        return {
            "id": record.id,
            "dataset_id": record.dataset_id,
            "objective": record.objective,
            "status": record.status,
            "outcome": record.outcome,
            "result_status": record.result_status,
            "feasible": record.feasible,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
        }

    @classmethod
    def _run_detail(cls, record: Any) -> Dict[str, Any]:
        detail = cls._run_summary(record)
        detail.update(
            {
                "params": record.params,
                "result": record.result,
                "schedule": record.schedule,
                "diagnostics": record.diagnostics,
                "error_code": record.error_code,
                "error_message": record.error_message,
            }
        )
        return detail

    def list_plans(self, dataset_id: Optional[str] = None) -> list:
        self._require_persistence()
        from aps_persistence.repositories import PlanningRunRepository

        with self._database.session() as session:
            records = PlanningRunRepository(session).list_records(
                dataset_id=dataset_id
            )
            return [self._run_summary(r) for r in records]

    def get_plan(self, plan_id: str) -> Dict[str, Any]:
        self._require_persistence()
        from aps_persistence.repositories import (
            PlanningRunNotFoundError,
            PlanningRunRepository,
        )

        with self._database.session() as session:
            try:
                record = PlanningRunRepository(session).require(plan_id)
            except PlanningRunNotFoundError as exc:
                raise NotFoundError(
                    "PLAN_NOT_FOUND", f"planning run {plan_id!r} was not found"
                ) from exc
            return self._run_detail(record)

    def _require_persistence(self) -> None:
        if self._database is None:
            raise RuntimeError(
                "persistence is not configured; run history is unavailable"
            )
