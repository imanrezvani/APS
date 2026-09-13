"""Dataset repository tests (Phase 10 P3).

Require a real PostgreSQL test database; skipped otherwise. The central
guarantee under test is a lossless domain -> repository -> domain round-trip
for the full generated dataset (calendar, maintenance/downtime, machines,
employees, materials/BOM/inventory, operations/routings and the
sequence-dependent setup matrix), plus the relational projection counts.
"""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from aps_engine.generator.generator import generate_dataset
from aps_persistence import models
from aps_persistence.repositories import DatasetNotFoundError, DatasetRepository

pytestmark = pytest.mark.usefixtures("migrated_database")


@pytest.fixture()
def session(migrated_database):
    engine = create_engine(migrated_database, future=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture()
def dataset():
    return generate_dataset(seed=7, sequence_dependent_setup=True)


def test_create_and_lossless_load(session, dataset):
    repo = DatasetRepository(session)
    record = repo.create(dataset, name="seeded", extra_meta={"origin": "test"})
    session.commit()

    assert record.id
    assert record.name == "seeded"
    assert record.format == "aps-engine.dataset.v1"
    assert len(record.sha256) == 64
    assert record.meta["origin"] == "test"
    assert record.meta["seed"] == 7

    loaded = repo.load(record.id)
    assert loaded == dataset
    assert loaded.setup_matrix == dataset.setup_matrix


def test_projection_matches_domain(session, dataset):
    repo = DatasetRepository(session)
    record = repo.create(dataset)
    session.commit()
    did = record.id

    def count(model):
        return session.scalar(
            select(func.count()).select_from(model).where(model.dataset_id == did)
        )

    assert count(models.WorkCenterRecord) == len(dataset.work_centers)
    assert count(models.MachineRecord) == len(dataset.machines)
    assert count(models.SkillRecord) == len(dataset.skills)
    assert count(models.ShiftRecord) == len(dataset.shifts)
    assert count(models.CalendarDayRecord) == len(dataset.calendar)
    assert count(models.EmployeeRecord) == len(dataset.employees)
    assert count(models.MaintenanceWindowRecord) == len(dataset.maintenance)
    assert count(models.DowntimeWindowRecord) == len(dataset.downtime)
    assert count(models.MaterialRecord) == len(dataset.materials)
    assert count(models.InventoryRecord) == len(dataset.inventory)
    assert count(models.ProductRecord) == len(dataset.products)
    assert count(models.BomRecord) == len(dataset.boms)
    assert count(models.BomItemRecord) == sum(
        len(bom.items) for bom in dataset.boms.values()
    )
    assert count(models.ProductionOrderRecord) == len(dataset.orders)
    assert count(models.OperationRecord) == len(dataset.operations)
    assert count(models.RoutingRecord) == len(dataset.routings)
    assert count(models.RoutingOperationRecord) == sum(
        len(routing.operations) for routing in dataset.routings.values()
    )
    assert count(models.SetupMatrixRecord) == len(dataset.setup_matrix)
    assert count(models.FactoryRecord) == 1

    total_machine_links = sum(
        len(op.allowed_machine_ids) for op in dataset.operations.values()
    )
    assert count(models.OperationMachineRecord) == total_machine_links
    assert count(models.EmployeeSkillRecord) == sum(
        len(e.skill_ids) for e in dataset.employees.values()
    )
    assert count(models.CalendarDayShiftRecord) == sum(
        len(d.shift_ids) for d in dataset.calendar
    )


def test_setup_matrix_persisted_exactly(session, dataset):
    repo = DatasetRepository(session)
    record = repo.create(dataset)
    session.commit()

    rows = session.scalars(
        select(models.SetupMatrixRecord).where(
            models.SetupMatrixRecord.dataset_id == record.id
        )
    )
    stored = {(r.from_family, r.to_family): r.minutes for r in rows}
    assert stored == dataset.setup_matrix


def test_list_and_find_by_sha256(session, dataset):
    repo = DatasetRepository(session)
    first = repo.create(dataset)
    second = repo.create(dataset)
    session.commit()

    assert {r.id for r in repo.list_records()} == {first.id, second.id}
    assert {r.id for r in repo.find_by_sha256(first.sha256)} == {first.id, second.id}


def test_delete_removes_dataset_and_projection(session, dataset):
    repo = DatasetRepository(session)
    record = repo.create(dataset)
    session.commit()
    did = record.id

    assert repo.delete(did) is True
    session.commit()

    assert repo.get_record(did) is None
    assert repo.delete(did) is False
    remaining_machines = session.scalar(
        select(func.count())
        .select_from(models.MachineRecord)
        .where(models.MachineRecord.dataset_id == did)
    )
    assert remaining_machines == 0


def test_replace_rebuilds_projection(session, dataset):
    repo = DatasetRepository(session)
    record = repo.create(dataset, name="before")
    session.commit()
    did = record.id

    smaller = generate_dataset(n_orders=3, seed=99)
    repo.replace(did, smaller, name="after")
    session.commit()

    assert repo.require_record(did).name == "after"
    assert repo.load(did) == smaller
    assert session.scalar(
        select(func.count())
        .select_from(models.MachineRecord)
        .where(models.MachineRecord.dataset_id == did)
    ) == len(smaller.machines)
    assert session.scalar(
        select(func.count())
        .select_from(models.ProductionOrderRecord)
        .where(models.ProductionOrderRecord.dataset_id == did)
    ) == len(smaller.orders)


def test_require_record_and_load_raise_for_unknown(session):
    repo = DatasetRepository(session)
    with pytest.raises(DatasetNotFoundError):
        repo.require_record("missing")
    with pytest.raises(DatasetNotFoundError):
        repo.load("missing")


def test_projection_is_scoped_per_dataset(session, dataset):
    repo = DatasetRepository(session)
    a = repo.create(dataset)
    smaller = generate_dataset(n_orders=2, seed=1)
    b = repo.create(smaller)
    session.commit()

    assert a.id != b.id
    a_machines = session.scalars(
        select(models.MachineRecord).where(models.MachineRecord.dataset_id == a.id)
    ).all()
    b_machines = session.scalars(
        select(models.MachineRecord).where(models.MachineRecord.dataset_id == b.id)
    ).all()
    assert all(row.dataset_id == a.id for row in a_machines)
    assert all(row.dataset_id == b.id for row in b_machines)
    assert len(a_machines) == len(dataset.machines)
    assert len(b_machines) == len(smaller.machines)
    assert repo.load(a.id) == dataset
    assert repo.load(b.id) == smaller
