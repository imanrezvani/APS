"""Dataset persistence repository (Phase 10 P3).

The repository is the single owner of all SQL for datasets. It receives an
explicit SQLAlchemy ``Session`` (never a global) and stores each dataset in
two coordinated forms:

* the canonical Phase 8 JSON document (``aps-engine.dataset.v1``) in
  ``datasets.doc``, used for a lossless :class:`~aps_engine.models.domain.Dataset`
  round-trip, and
* a normalized relational projection (work centers, machines, employees,
  shifts/calendar, maintenance/downtime, materials, BOMs, inventory,
  products, orders, operations, routings and the setup matrix) for querying.

The application service owns orchestration and transaction boundaries; the
repository only adds/flushes objects and maps rows to the domain.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from json import loads
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from aps_engine.io.dataset_io import FORMAT, dataset_from_json, dataset_to_json
from aps_engine.models.domain import Dataset
from aps_persistence.models import (
    BomItemRecord,
    BomRecord,
    CalendarDayRecord,
    CalendarDayShiftRecord,
    DatasetRecord,
    DowntimeWindowRecord,
    EmployeeRecord,
    EmployeeShiftRecord,
    EmployeeSkillRecord,
    EmployeeWorkCenterRecord,
    FactoryRecord,
    InventoryRecord,
    MachineRecord,
    MaintenanceWindowRecord,
    MaterialRecord,
    OperationMachineRecord,
    OperationRecord,
    ProductRecord,
    ProductionOrderRecord,
    RoutingOperationRecord,
    RoutingRecord,
    SetupMatrixRecord,
    ShiftRecord,
    SkillRecord,
    WorkCenterRecord,
)


class DatasetNotFoundError(KeyError):
    """Raised when a requested dataset id does not exist."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_document(dataset: Dataset) -> tuple[Dict[str, Any], str]:
    """Return the canonical JSON-safe document and its serialized text."""
    text = dataset_to_json(dataset)
    return loads(text), text


class DatasetRepository:
    """Persistence operations for :class:`~aps_engine.models.domain.Dataset`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- writes ---------------------------------------------------------

    def create(
        self,
        dataset: Dataset,
        *,
        dataset_id: Optional[str] = None,
        name: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> DatasetRecord:
        """Persist ``dataset`` (canonical doc + normalized projection).

        The stored ``doc`` is the engine-produced canonical document, so a
        later :meth:`load` rebuilds a dataset equal to ``dataset``. The
        returned record is flushed/refreshed so server defaults (timestamps)
        are populated.
        """
        document, text = _canonical_document(dataset)
        resolved_id = dataset_id or str(uuid4())
        meta = dict(dataset.meta)
        if extra_meta:
            meta.update(extra_meta)

        record = DatasetRecord(
            id=resolved_id,
            name=name or self._default_name(dataset),
            format=FORMAT,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            doc=document,
            meta=meta,
        )
        self.session.add(record)
        self.session.flush()
        self._project(resolved_id, dataset)
        self.session.flush()
        self.session.refresh(record)
        return record

    def replace(
        self,
        dataset_id: str,
        dataset: Dataset,
        *,
        name: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> DatasetRecord:
        """Overwrite an existing dataset (projection rows are rebuilt)."""
        record = self.get_record(dataset_id)
        if record is None:
            raise DatasetNotFoundError(dataset_id)

        self._clear_projection(dataset_id)
        document, text = _canonical_document(dataset)
        meta = dict(dataset.meta)
        if extra_meta:
            meta.update(extra_meta)
        if name is not None:
            record.name = name
        record.format = FORMAT
        record.sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        record.doc = document
        record.meta = meta
        record.updated_at = _utcnow()
        self._project(dataset_id, dataset)
        self.session.flush()
        self.session.refresh(record)
        return record

    def delete(self, dataset_id: str) -> bool:
        """Delete a dataset and (via FK cascade) its projection rows."""
        record = self.get_record(dataset_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True

    # -- reads ----------------------------------------------------------

    def get_record(self, dataset_id: str) -> Optional[DatasetRecord]:
        return self.session.get(DatasetRecord, dataset_id)

    def require_record(self, dataset_id: str) -> DatasetRecord:
        record = self.get_record(dataset_id)
        if record is None:
            raise DatasetNotFoundError(dataset_id)
        return record

    def load(self, dataset_id: str) -> Dataset:
        """Rebuild the exact domain :class:`Dataset` from the stored doc."""
        record = self.require_record(dataset_id)
        return dataset_from_json(record.doc)

    def list_records(self) -> List[DatasetRecord]:
        stmt = select(DatasetRecord).order_by(DatasetRecord.created_at, DatasetRecord.id)
        return list(self.session.scalars(stmt))

    def find_by_sha256(self, sha256: str) -> List[DatasetRecord]:
        stmt = (
            select(DatasetRecord)
            .where(DatasetRecord.sha256 == sha256)
            .order_by(DatasetRecord.created_at, DatasetRecord.id)
        )
        return list(self.session.scalars(stmt))

    # -- internals ------------------------------------------------------

    @staticmethod
    def _default_name(dataset: Dataset) -> Optional[str]:
        for key in ("name", "dataset_name", "title"):
            value = dataset.meta.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _clear_projection(self, dataset_id: str) -> None:
        for model in _PROJECTION_MODELS:
            for row in self.session.scalars(
                select(model).where(model.dataset_id == dataset_id)
            ):
                self.session.delete(row)

    def _project(self, dataset_id: str, ds: Dataset) -> None:
        session = self.session
        session.add(
            FactoryRecord(
                dataset_id=dataset_id,
                name=self._default_name(ds) or "factory",
                meta=dict(ds.meta),
            )
        )

        for wc in ds.work_centers.values():
            session.add(WorkCenterRecord(dataset_id=dataset_id, id=wc.id, name=wc.name))
        for machine in ds.machines.values():
            session.add(
                MachineRecord(
                    dataset_id=dataset_id,
                    id=machine.id,
                    name=machine.name,
                    work_center_id=machine.work_center_id,
                )
            )
        for skill in ds.skills.values():
            session.add(SkillRecord(dataset_id=dataset_id, id=skill.id, name=skill.name))
        for shift in ds.shifts.values():
            session.add(
                ShiftRecord(
                    dataset_id=dataset_id,
                    id=shift.id,
                    name=shift.name,
                    start_minute=shift.start_minute,
                    end_minute=shift.end_minute,
                )
            )
        for day in ds.calendar:
            session.add(
                CalendarDayRecord(
                    dataset_id=dataset_id,
                    day_index=day.day_index,
                    is_working=day.is_working,
                )
            )
            for shift_id in day.shift_ids:
                session.add(
                    CalendarDayShiftRecord(
                        dataset_id=dataset_id,
                        day_index=day.day_index,
                        shift_id=shift_id,
                    )
                )
        for employee in ds.employees.values():
            session.add(
                EmployeeRecord(
                    dataset_id=dataset_id,
                    id=employee.id,
                    name=employee.name,
                    available_from=employee.available_from,
                    available_until=employee.available_until,
                )
            )
            for skill_id in employee.skill_ids:
                session.add(
                    EmployeeSkillRecord(
                        dataset_id=dataset_id, employee_id=employee.id, skill_id=skill_id
                    )
                )
            for wc_id in employee.work_center_ids:
                session.add(
                    EmployeeWorkCenterRecord(
                        dataset_id=dataset_id,
                        employee_id=employee.id,
                        work_center_id=wc_id,
                    )
                )
            for shift_id in employee.shift_ids:
                session.add(
                    EmployeeShiftRecord(
                        dataset_id=dataset_id, employee_id=employee.id, shift_id=shift_id
                    )
                )
        for window in ds.maintenance:
            session.add(
                MaintenanceWindowRecord(
                    dataset_id=dataset_id,
                    machine_id=window.machine_id,
                    start=window.start,
                    end=window.end,
                    reason=window.reason,
                )
            )
        for window in ds.downtime:
            session.add(
                DowntimeWindowRecord(
                    dataset_id=dataset_id,
                    machine_id=window.machine_id,
                    start=window.start,
                    end=window.end,
                    reason=window.reason,
                )
            )
        for material in ds.materials.values():
            session.add(
                MaterialRecord(
                    dataset_id=dataset_id,
                    id=material.id,
                    name=material.name,
                    unit=material.unit,
                )
            )
        for item in ds.inventory.values():
            session.add(
                InventoryRecord(
                    dataset_id=dataset_id,
                    material_id=item.material_id,
                    on_hand=item.on_hand,
                )
            )
        for product in ds.products.values():
            session.add(
                ProductRecord(dataset_id=dataset_id, id=product.id, name=product.name)
            )
        for product_id, bom in ds.boms.items():
            session.add(BomRecord(dataset_id=dataset_id, product_id=product_id))
            for item in bom.items:
                session.add(
                    BomItemRecord(
                        dataset_id=dataset_id,
                        product_id=product_id,
                        material_id=item.material_id,
                        quantity_per_unit=item.quantity_per_unit,
                    )
                )
        for order in ds.orders.values():
            session.add(
                ProductionOrderRecord(
                    dataset_id=dataset_id,
                    id=order.id,
                    product_id=order.product_id,
                    quantity=order.quantity,
                    release_time=order.release_time,
                    due_time=order.due_time,
                    priority=order.priority,
                )
            )
        for op in ds.operations.values():
            session.add(
                OperationRecord(
                    dataset_id=dataset_id,
                    id=op.id,
                    order_id=op.order_id,
                    sequence=op.sequence,
                    work_center_id=op.work_center_id,
                    processing_time=op.processing_time,
                    setup_time=op.setup_time,
                    setup_family_id=op.setup_family_id,
                    required_skill_id=op.required_skill_id,
                    employee_required=op.employee_required,
                )
            )
            for machine_id in op.allowed_machine_ids:
                session.add(
                    OperationMachineRecord(
                        dataset_id=dataset_id,
                        operation_id=op.id,
                        machine_id=machine_id,
                    )
                )
        for routing_id, routing in ds.routings.items():
            session.add(
                RoutingRecord(
                    dataset_id=dataset_id, id=routing_id, product_id=routing.product_id
                )
            )
            for position, operation_id in enumerate(routing.operations):
                session.add(
                    RoutingOperationRecord(
                        dataset_id=dataset_id,
                        routing_id=routing_id,
                        position=position,
                        operation_id=operation_id,
                    )
                )
        for (from_family, to_family), minutes in sorted(ds.setup_matrix.items()):
            session.add(
                SetupMatrixRecord(
                    dataset_id=dataset_id,
                    from_family=from_family,
                    to_family=to_family,
                    minutes=minutes,
                )
            )


# Tables that belong to a dataset and must be cleared on replace/delete.
_PROJECTION_MODELS = (
    BomItemRecord,
    BomRecord,
    CalendarDayShiftRecord,
    CalendarDayRecord,
    DowntimeWindowRecord,
    EmployeeShiftRecord,
    EmployeeSkillRecord,
    EmployeeWorkCenterRecord,
    EmployeeRecord,
    InventoryRecord,
    MachineRecord,
    MaintenanceWindowRecord,
    MaterialRecord,
    OperationMachineRecord,
    OperationRecord,
    ProductRecord,
    ProductionOrderRecord,
    RoutingOperationRecord,
    RoutingRecord,
    SetupMatrixRecord,
    ShiftRecord,
    SkillRecord,
    WorkCenterRecord,
    FactoryRecord,
)

__all__ = ["DatasetRepository", "DatasetNotFoundError"]
