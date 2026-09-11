"""Schema and model-level tests for the Phase 10 persistence models (P2).

These tests require a real PostgreSQL test database (the models use the
PostgreSQL ``JSONB`` type) and are skipped when it is unavailable. They verify
that the Alembic migration produces exactly the tables the ORM metadata
declares, that dataset-scoped foreign keys enforce their cascade rules, and
that the pure outcome classifier used by repositories is correct.
"""

import pytest

from aps_persistence import models
from aps_persistence.base import Base

pytestmark = pytest.mark.usefixtures("migrated_database")

DATASET_TABLES = {
    "datasets",
    "factories",
    "work_centers",
    "machines",
    "shifts",
    "calendar_days",
    "calendar_day_shifts",
    "skills",
    "employees",
    "employee_skills",
    "employee_work_centers",
    "employee_shifts",
    "maintenance_windows",
    "downtime_windows",
    "materials",
    "inventory",
    "products",
    "boms",
    "bom_items",
    "production_orders",
    "operations",
    "operation_machines",
    "routings",
    "routing_operations",
    "setup_matrix",
    "planning_runs",
}


def test_metadata_declares_expected_tables():
    assert set(Base.metadata.tables) == DATASET_TABLES


def test_migration_creates_metadata_tables(migrated_database):
    from sqlalchemy import create_engine, inspect

    engine = create_engine(migrated_database, future=True)
    try:
        actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()
    assert actual == set(Base.metadata.tables)


def test_dataset_owned_tables_carry_dataset_fk():
    for table in Base.metadata.tables.values():
        if table.name == "datasets":
            continue
        assert "dataset_id" in table.columns, table.name


def test_dataset_owned_fks_cascade_on_delete():
    for table in Base.metadata.tables.values():
        if table.name == "datasets":
            continue
        fk = next(
            fk
            for fk in table.foreign_keys
            if fk.parent.name == "dataset_id"
        )
        expected = "RESTRICT" if table.name == "planning_runs" else "CASCADE"
        assert fk.ondelete == expected, table.name


def test_dataset_row_and_jsonb_roundtrip(migrated_database):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    engine = create_engine(migrated_database, future=True)
    try:
        with Session(engine) as session:
            session.add(
                models.DatasetRecord(
                    id="ds-1",
                    name="demo",
                    format="aps-engine.dataset.v1",
                    sha256="a" * 64,
                    doc={"format": "aps-engine.dataset.v1", "meta": {"nested": [1, 2]}},
                )
            )
            session.commit()

        with Session(engine) as session:
            record = session.get(models.DatasetRecord, "ds-1")
            assert record.doc == {"format": "aps-engine.dataset.v1", "meta": {"nested": [1, 2]}}
            assert record.created_at is not None
            assert record.meta == {}
            assert session.scalars(select(models.DatasetRecord)).one().name == "demo"
    finally:
        engine.dispose()


def test_delete_dataset_cascades_to_children(migrated_database):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    engine = create_engine(migrated_database, future=True)
    try:
        with Session(engine) as session:
            session.add(
                models.DatasetRecord(
                    id="ds-cascade",
                    format="aps-engine.dataset.v1",
                    sha256="b" * 64,
                    doc={},
                )
            )
            session.add(
                models.MachineRecord(
                    dataset_id="ds-cascade", id="m1", name="Mill", work_center_id="wc1"
                )
            )
            session.add(
                models.MaintenanceWindowRecord(
                    dataset_id="ds-cascade", machine_id="m1", start=0, end=60
                )
            )
            session.commit()

        with Session(engine) as session:
            session.delete(session.get(models.DatasetRecord, "ds-cascade"))
            session.commit()

        with Session(engine) as session:
            assert session.scalar(
                select(func.count()).select_from(models.MachineRecord)
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(models.MaintenanceWindowRecord)
            ) == 0
    finally:
        engine.dispose()


def test_planning_run_defaults_and_jsonb(migrated_database):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(migrated_database, future=True)
    try:
        with Session(engine) as session:
            session.add(
                models.DatasetRecord(
                    id="ds-run",
                    format="aps-engine.dataset.v1",
                    sha256="c" * 64,
                    doc={},
                )
            )
            session.commit()

        with Session(engine) as session:
            run = models.PlanningRunRecord(
                id="run-1",
                dataset_id="ds-run",
                objective="weighted_tardiness",
                params={"time_limit_seconds": 30},
                diagnostics=[{"code": "X", "message": "y"}],
                result={"format": "aps-engine.result.v1"},
                schedule={"assignments": []},
            )
            session.add(run)
            session.commit()

        with Session(engine) as session:
            stored = session.get(models.PlanningRunRecord, "run-1")
            assert stored.status == models.RUN_PENDING
            assert stored.outcome is None
            assert stored.diagnostics == [{"code": "X", "message": "y"}]
            assert stored.result == {"format": "aps-engine.result.v1"}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "success,feasible,result_status,error_code,expected",
    [
        (True, True, "OPTIMAL", None, models.OUTCOME_OPTIMAL),
        (True, True, "FEASIBLE", None, models.OUTCOME_FEASIBLE),
        (True, False, "INFEASIBLE", None, models.OUTCOME_INFEASIBLE),
        (False, None, None, "INVALID_DATASET_DOCUMENT", models.OUTCOME_INVALID_REQUEST),
        (False, None, None, "UNKNOWN_OBJECTIVE", models.OUTCOME_INVALID_REQUEST),
        (False, None, None, "VALIDATION_ERROR", models.OUTCOME_INVALID_REQUEST),
        (False, None, None, "EXECUTION_ERROR", models.OUTCOME_EXECUTION_FAILURE),
    ],
)
def test_classify_outcome(success, feasible, result_status, error_code, expected):
    assert (
        models.classify_outcome(
            success=success,
            feasible=feasible,
            result_status=result_status,
            error_code=error_code,
        )
        == expected
    )
