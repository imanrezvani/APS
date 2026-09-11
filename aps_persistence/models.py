"""Relational persistence models for the APS dataset and planning runs
(Phase 10 P2).

The models are a persistence *read/write* representation of the Phase 1-9
domain dataset plus the Phase 10 ``PlanningRun``. They are deliberately
decoupled from the engine: no domain dataclass is changed and the solver
never imports this module.

Two layers are stored per dataset:

* ``datasets.doc`` holds the canonical Phase 8 dataset JSON document
  (``aps-engine.dataset.v1``) emitted by
  :func:`aps_engine.io.dataset_io.dataset_to_json`. It is the lossless
  source of truth used to rebuild the exact ``Dataset`` the engine solves,
  so planning semantics can never be lost by the relational mapping.
* The normalized tables (work centers, machines, employees/skills,
  shifts/calendar, maintenance/downtime, materials, BOM/BOM items,
  inventory, products, production orders, operations, routings and the
  setup/changeover matrix) provide a queryable relational projection of the
  same data.

Every dataset-owned table carries a ``dataset_id`` foreign key. That scope
column is the seam for a future phase to support physical database-per-tenant
isolation (one database/session factory per tenant) without changing
repositories or business logic. Phase 10 implements no tenants, no RLS and no
tenant routing.

PlanningRun persists only the JSON-safe Phase 8 ResultDocument content
(``result``, ``schedule``, ``diagnostics``); CP-SAT/solver internals are
never stored. Its lifecycle columns distinguish a feasible/optimal run, a
valid infeasible result, a rejected invalid request and an unexpected
execution failure.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aps_persistence.base import Base

# PlanningRun lifecycle status.
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

# PlanningRun outcome classification.
OUTCOME_OPTIMAL = "optimal"
OUTCOME_FEASIBLE = "feasible"
OUTCOME_INFEASIBLE = "infeasible"
OUTCOME_INVALID_REQUEST = "invalid_request"
OUTCOME_EXECUTION_FAILURE = "execution_failure"

# Error codes that mark a rejected (invalid) request rather than a failure.
INVALID_REQUEST_CODES = frozenset(
    {"INVALID_DATASET_DOCUMENT", "UNKNOWN_OBJECTIVE", "VALIDATION_ERROR"}
)


def _dataset_id(*, primary_key: bool = False) -> Mapped[str]:
    """A ``dataset_id`` foreign key column scoped to ``datasets.id``."""
    return mapped_column(
        String(36),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
        index=True,
    )


class DatasetRecord(Base):
    """A persisted dataset: metadata + the canonical Phase 8 JSON document."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    doc: Mapped[dict] = mapped_column(JSONB, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    runs = relationship("PlanningRunRecord", back_populates="dataset")


class FactoryRecord(Base):
    """The factory scope of a dataset (one row per dataset).

    The Phase 1-9 domain has no explicit Factory entity, so this row records
    the dataset's factory-level identity from the free-form ``meta`` and
    keeps a stable scope for future factory configuration.
    """

    __tablename__ = "factories"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class WorkCenterRecord(Base):
    __tablename__ = "work_centers"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class MachineRecord(Base):
    __tablename__ = "machines"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_center_id: Mapped[str] = mapped_column(String(64), nullable=False)


class ShiftRecord(Base):
    __tablename__ = "shifts"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)


class CalendarDayRecord(Base):
    __tablename__ = "calendar_days"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_working: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CalendarDayShiftRecord(Base):
    __tablename__ = "calendar_day_shifts"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class SkillRecord(Base):
    __tablename__ = "skills"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class EmployeeRecord(Base):
    __tablename__ = "employees"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    available_from: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_until: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EmployeeSkillRecord(Base):
    __tablename__ = "employee_skills"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class EmployeeWorkCenterRecord(Base):
    __tablename__ = "employee_work_centers"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    work_center_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class EmployeeShiftRecord(Base):
    __tablename__ = "employee_shifts"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shift_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class MaintenanceWindowRecord(Base):
    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = _dataset_id()
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="maintenance")


class DowntimeWindowRecord(Base):
    __tablename__ = "downtime_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = _dataset_id()
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="downtime")


class MaterialRecord(Base):
    __tablename__ = "materials"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="unit")


class InventoryRecord(Base):
    __tablename__ = "inventory"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    material_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    on_hand: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class ProductRecord(Base):
    __tablename__ = "products"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class BomRecord(Base):
    __tablename__ = "boms"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class BomItemRecord(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = _dataset_id()
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    material_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity_per_unit: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class ProductionOrderRecord(Base):
    __tablename__ = "production_orders"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    release_time: Mapped[int] = mapped_column(Integer, nullable=False)
    due_time: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OperationRecord(Base):
    __tablename__ = "operations"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    work_center_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_time: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    setup_family_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    required_skill_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    employee_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OperationMachineRecord(Base):
    __tablename__ = "operation_machines"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class RoutingRecord(Base):
    __tablename__ = "routings"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)


class RoutingOperationRecord(Base):
    __tablename__ = "routing_operations"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    routing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)


class SetupMatrixRecord(Base):
    __tablename__ = "setup_matrix"

    dataset_id: Mapped[str] = _dataset_id(primary_key=True)
    from_family: Mapped[str] = mapped_column(String(64), primary_key=True)
    to_family: Mapped[str] = mapped_column(String(64), primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)


class PlanningRunRecord(Base):
    """A persisted planning run (the Phase 8 ResultDocument, JSON-safe)."""

    __tablename__ = "planning_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="RESTRICT"), index=True
    )
    objective: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RUN_PENDING)
    outcome: Mapped[Optional[str]] = mapped_column(String(32))
    result_status: Mapped[Optional[str]] = mapped_column(String(32))
    feasible: Mapped[Optional[bool]] = mapped_column(Boolean)
    result: Mapped[Optional[dict]] = mapped_column(JSONB)
    schedule: Mapped[Optional[dict]] = mapped_column(JSONB)
    diagnostics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    root_cause: Mapped[Optional[str]] = mapped_column(String(64))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    dataset = relationship("DatasetRecord", back_populates="runs")


def classify_outcome(
    *, success: bool, feasible: Optional[bool], result_status: Optional[str],
    error_code: Optional[str],
) -> str:
    """Classify a run into one of the persisted outcome categories."""
    if not success:
        if error_code in INVALID_REQUEST_CODES:
            return OUTCOME_INVALID_REQUEST
        return OUTCOME_EXECUTION_FAILURE
    if feasible:
        return OUTCOME_OPTIMAL if result_status == "OPTIMAL" else OUTCOME_FEASIBLE
    return OUTCOME_INFEASIBLE


__all__ = [
    "Base",
    "BomItemRecord",
    "BomRecord",
    "CalendarDayRecord",
    "CalendarDayShiftRecord",
    "DatasetRecord",
    "DowntimeWindowRecord",
    "EmployeeRecord",
    "EmployeeShiftRecord",
    "EmployeeSkillRecord",
    "EmployeeWorkCenterRecord",
    "FactoryRecord",
    "INVALID_REQUEST_CODES",
    "InventoryRecord",
    "MachineRecord",
    "MaintenanceWindowRecord",
    "MaterialRecord",
    "OperationMachineRecord",
    "OperationRecord",
    "OUTCOME_EXECUTION_FAILURE",
    "OUTCOME_FEASIBLE",
    "OUTCOME_INFEASIBLE",
    "OUTCOME_INVALID_REQUEST",
    "OUTCOME_OPTIMAL",
    "PlanningRunRecord",
    "ProductRecord",
    "ProductionOrderRecord",
    "RoutingOperationRecord",
    "RoutingRecord",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_PENDING",
    "RUN_RUNNING",
    "SetupMatrixRecord",
    "ShiftRecord",
    "SkillRecord",
    "WorkCenterRecord",
    "classify_outcome",
]
