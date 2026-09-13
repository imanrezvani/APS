"""PlanningRun persistence repository (Phase 10 P4).

A planning run records the JSON-safe Phase 8 result document plus its
lifecycle. Only JSON-safe content is stored (never CP-SAT/solver internals),
so :meth:`PlanningRunRepository.load_result` can rebuild the exact
``{"result": SolveResult, "schedule": ...}`` output with
``aps_engine.io.result_io.result_from_json``.

Outcomes are classified by :func:`aps_persistence.models.classify_outcome`:

* ``optimal`` / ``feasible``        -> completed run with a schedule
* ``infeasible``                    -> completed run, valid result, no schedule
* ``invalid_request``               -> rejected request (bad dataset/objective)
* ``execution_failure``             -> unexpected execution error
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from aps_engine.io.result_io import FORMAT, result_from_json
from aps_persistence.models import (
    DatasetRecord,
    PlanningRunRecord,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
    classify_outcome,
)


class PlanningRunNotFoundError(KeyError):
    """Raised when a requested planning run id does not exist."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlanningRunRepository:
    """Persistence operations for :class:`PlanningRunRecord`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- lifecycle ------------------------------------------------------

    def start(
        self,
        *,
        dataset_id: Optional[str],
        objective: str,
        params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> PlanningRunRecord:
        """Create a run in the ``running`` state and stamp ``started_at``."""
        run = PlanningRunRecord(
            id=run_id or str(uuid4()),
            dataset_id=dataset_id,
            objective=objective,
            params=dict(params or {}),
            status=RUN_RUNNING,
            started_at=_utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def create_pending(
        self,
        *,
        dataset_id: Optional[str],
        objective: str,
        params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> PlanningRunRecord:
        """Create a run in the ``pending`` state (not yet started)."""
        run = PlanningRunRecord(
            id=run_id or str(uuid4()),
            dataset_id=dataset_id,
            objective=objective,
            params=dict(params or {}),
            status=RUN_PENDING,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete(
        self, run: PlanningRunRecord, payload: Dict[str, Any]
    ) -> PlanningRunRecord:
        """Persist a successful execution payload and classify the outcome.

        ``payload`` is the ``{"result": {json}, "schedule": ...}`` dict
        produced by the API executor (already JSON-safe). An infeasible
        result is stored as a completed run (not an error).
        """
        result = dict(payload["result"])
        run.result = result
        run.schedule = payload.get("schedule")
        run.diagnostics = result.get("diagnostics") or []
        run.result_status = result.get("status")
        run.feasible = result.get("feasible")
        run.status = RUN_COMPLETED
        run.outcome = classify_outcome(
            success=True,
            feasible=run.feasible,
            result_status=run.result_status,
            error_code=None,
        )
        run.completed_at = _utcnow()
        self.session.flush()
        return run

    def fail(
        self,
        run: PlanningRunRecord,
        *,
        error_code: str,
        error_message: str,
    ) -> PlanningRunRecord:
        """Persist a failed/rejected run and classify the outcome."""
        run.status = RUN_FAILED
        run.error_code = error_code
        run.error_message = error_message
        run.outcome = classify_outcome(
            success=False,
            feasible=None,
            result_status=None,
            error_code=error_code,
        )
        run.completed_at = _utcnow()
        self.session.flush()
        return run

    # -- reads ----------------------------------------------------------

    def get(self, run_id: str) -> Optional[PlanningRunRecord]:
        return self.session.get(PlanningRunRecord, run_id)

    def require(self, run_id: str) -> PlanningRunRecord:
        run = self.get(run_id)
        if run is None:
            raise PlanningRunNotFoundError(run_id)
        return run

    def list_records(self, *, dataset_id: Optional[str] = None) -> List[PlanningRunRecord]:
        stmt = select(PlanningRunRecord)
        if dataset_id is not None:
            stmt = stmt.where(PlanningRunRecord.dataset_id == dataset_id)
        stmt = stmt.order_by(PlanningRunRecord.created_at, PlanningRunRecord.id)
        return list(self.session.scalars(stmt))

    def load_result(self, run_id: str) -> Dict[str, Any]:
        """Rebuild the JSON-safe solve output for a completed run.

        Returns ``{"result": SolveResult, "schedule": ...}`` exactly as
        :func:`aps_engine.io.result_io.result_from_json`. Raises
        :class:`PlanningRunNotFoundError` for an unknown run and
        ``ValueError`` for a run that has no persisted result.
        """
        run = self.require(run_id)
        if run.result is None:
            raise ValueError(f"planning run {run_id!r} has no persisted result")
        return result_from_json(
            {"format": FORMAT, "result": run.result, "schedule": run.schedule}
        )

    # -- helpers --------------------------------------------------------

    def dataset_record(self, run: PlanningRunRecord) -> Optional[DatasetRecord]:
        if run.dataset_id is None:
            return None
        return self.session.get(DatasetRecord, run.dataset_id)


__all__ = ["PlanningRunRepository", "PlanningRunNotFoundError"]
