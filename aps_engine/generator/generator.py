"""Deterministic synthetic dataset generator (Phase 3).

10 orders, 5 products, 4 work centers, 8 machines, 3-5 operations per order,
a factory calendar (shifts, weekly pattern, one extra holiday), machine
unavailability windows (maintenance + downtime) and 9 employees with skills,
work-center authorization, shifts and availability. Reproducible with
seed = 42.

Default calendar (time is integer minutes since the start of day 0):
  Mon-Fri   Shift A 08:00-16:00, Shift B 16:00-24:00
  Sat       Shift A 08:00-16:00
  Sun       holiday (off)
  day 3     extra holiday (off)

Due dates are kept tight so the calendar actually constrains the schedule:
orders released late in a shift must complete in later shifts (and can never
run on holidays), and machine maintenance / downtime windows must be avoided.

Employee resource contention is genuine: only 2 employees are CNC-qualified
(one per shift) while the dataset contains 6 CNC operations, so CNC work is a
real bottleneck. Edge banding B is unavailable on Monday, exercising the
availability constraint.

Materials and on-hand inventory (Phase 4.2): 6 furniture materials, each with
a deterministic on-hand quantity. M_HINGE carries deliberately limited stock
so future material-availability solver tests can drive a shortage. The default
dataset is intentionally material-infeasible at the order-book level.

BOMs (Phase 4.3): every generated product has a bill of materials connecting
Product -> BOM -> Material with strictly positive per-unit quantities,
including both single-material (P_SHELF) and multi-material BOMs.

Material-feasible variant (Phase 4.7 Part 2): ``material_feasible=True`` on
``generate_dataset`` raises every on-hand quantity to exactly cover the whole
order book's aggregated demand, keeping BOMs, products, orders, and all
scheduling data unchanged. The default stays material-infeasible.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from aps_engine.models import (
    BOM,
    BomItem,
    CalendarDay,
    Dataset,
    DowntimeWindow,
    Employee,
    Machine,
    MaintenanceWindow,
    Material,
    MaterialInventory,
    Operation,
    Order,
    Product,
    Routing,
    Shift,
    Skill,
    WorkCenter,
)

# step -> (work_center_id, base minutes, minutes per unit)
STEPS = {
    "CUT": ("WC_CUTTING", 10, 0.5),
    "EDGE": ("WC_EDGE_BANDING", 8, 0.4),
    "CNC": ("WC_CNC", 12, 0.6),
    "ASM": ("WC_ASSEMBLY", 15, 0.8),
}

# step -> required skill id
STEP_SKILL = {
    "CUT": "CUTTING",
    "EDGE": "EDGE_BANDING",
    "CNC": "CNC",
    "ASM": "ASSEMBLY",
}

# skill id -> setup time (machine changeover before the operation starts)
SETUP_TIMES = {
    "CUTTING": 15,
    "EDGE_BANDING": 15,
    "CNC": 20,
    "ASSEMBLY": 10,
}

# skill id -> (name)
SKILLS = {
    "CUTTING": "Cutting",
    "EDGE_BANDING": "Edge banding",
    "CNC": "CNC machining",
    "ASSEMBLY": "Assembly",
}

# --- materials + inventory (Phase 4.2) ---------------------------------------
# (id, name, unit)
MATERIALS: List[Tuple[str, str, str]] = [
    ("M_BOARD", "Particle board", "sheet"),
    ("M_EDGE", "Edge tape", "meter"),
    ("M_HINGE", "Hinge", "pcs"),
    ("M_SCREW", "Screw pack", "box"),
    ("M_GLUE", "PVA glue", "liter"),
    ("M_PACK", "Packaging set", "set"),
]

# (material_id, on_hand) - M_HINGE carries deliberately limited stock so
# future material-availability solver tests can drive a shortage.
INVENTORY: List[Tuple[str, int]] = [
    ("M_BOARD", 120),
    ("M_EDGE", 400),
    ("M_HINGE", 30),
    ("M_SCREW", 50),
    ("M_GLUE", 40),
    ("M_PACK", 60),
]

# product id -> BOM as [(material_id, quantity_per_unit), ...]. Every material
# is defined in MATERIALS; quantities are strictly positive. P_SHELF is a
# single-material BOM, the others are multi-material.
BOMS: Dict[str, List[Tuple[str, float]]] = {
    "P_CABINET": [("M_BOARD", 2.0), ("M_EDGE", 8.0), ("M_HINGE", 4.0),
                  ("M_SCREW", 1.0), ("M_GLUE", 0.5), ("M_PACK", 1.0)],
    "P_WARDROBE": [("M_BOARD", 3.0), ("M_EDGE", 12.0), ("M_HINGE", 4.0),
                   ("M_SCREW", 1.0), ("M_PACK", 1.0)],
    "P_DESK": [("M_BOARD", 1.5), ("M_EDGE", 6.0), ("M_SCREW", 0.5),
               ("M_GLUE", 0.2)],
    "P_TV_STAND": [("M_BOARD", 1.0), ("M_GLUE", 0.1), ("M_PACK", 0.5)],
    "P_SHELF": [("M_BOARD", 0.5)],
}

# product id -> routing template (ordered step names)
PRODUCTS = {
    "P_CABINET": ["CUT", "EDGE", "CNC", "ASM"],
    "P_WARDROBE": ["CUT", "EDGE", "CNC", "ASM"],
    "P_DESK": ["CUT", "EDGE", "ASM"],
    "P_TV_STAND": ["CUT", "CNC", "ASM"],
    "P_SHELF": ["CUT", "EDGE", "ASM"],
}

WORK_CENTERS = {
    "WC_CUTTING": ("Cutting", ["CUT-1", "CUT-2"]),
    "WC_EDGE_BANDING": ("Edge banding", ["EDGE-1", "EDGE-2"]),
    "WC_CNC": ("CNC machining", ["CNC-1", "CNC-2"]),
    "WC_ASSEMBLY": ("Assembly", ["ASM-1", "ASM-2"]),
}

N_ORDERS = 10
SEED = 42

# --- factory calendar (Phase 2) ---------------------------------------------
N_DAYS = 14
DAY_MINUTES = 1440
EXTRA_HOLIDAY_DAY = 3  # Thursday of week 1: plant-wide holiday

# absolute-minute maintenance / downtime windows (avoid ASM-1, the only
# machine that can assemble DESK orders)
MAINTENANCE: List[Tuple[str, int, int]] = [
    ("CUT-1", 540, 720),                # Mon 09:00-12:00
    ("EDGE-2", 600, 780),               # Mon 10:00-13:00
    ("CNC-1", 720, 900),                # Mon 12:00-15:00
    ("ASM-2", DAY_MINUTES + 540, DAY_MINUTES + 720),  # Tue 09:00-12:00
]
DOWNTIME: List[Tuple[str, int, int]] = [
    ("CUT-2", 1020, 1140),              # Mon 17:00-19:00
    ("CNC-2", DAY_MINUTES + 600, DAY_MINUTES + 660),  # Tue 10:00-11:00
]

# per-priority due slack (minutes): how much extra beyond total processing time
# an order gets before it is considered late
DUE_SLACK = {3: 0, 2: 120, 1: 300}

# --- employees (Phase 3) -----------------------------------------------------
# (id, name, shift_ids, skill_ids, work_center_ids, available_from, available_until)
# available_until = 0 -> full horizon (resolved when building the dataset)
EMPLOYEES: List[Tuple[str, str, List[str], List[str], List[str], int, int]] = [
    ("E_CUT_A", "Cutting A", ["A", "B"], ["CUTTING"], ["WC_CUTTING"], 0, 0),
    ("E_CUT_B", "Cutting B", ["A"], ["CUTTING"], ["WC_CUTTING"], 0, 0),
    ("E_EDGE_A", "Edge banding A", ["A", "B"], ["EDGE_BANDING"], ["WC_EDGE_BANDING"], 0, 0),
    ("E_EDGE_B", "Edge banding B", ["B"], ["EDGE_BANDING"], ["WC_EDGE_BANDING"], DAY_MINUTES, 0),
    ("E_CNC_A", "CNC A", ["A"], ["CNC"], ["WC_CNC"], 0, 0),
    ("E_CNC_B", "CNC B", ["B"], ["CNC"], ["WC_CNC"], 0, 0),
    ("E_ASM_A", "Assembly A", ["A", "B"], ["ASSEMBLY"], ["WC_ASSEMBLY"], 0, 0),
    ("E_ASM_B", "Assembly B", ["A"], ["ASSEMBLY"], ["WC_ASSEMBLY"], 0, 0),
    ("E_FLEX", "Flexible", ["A", "B"], ["CUTTING", "EDGE_BANDING"],
     ["WC_CUTTING", "WC_EDGE_BANDING"], 0, 0),
]


def _build_shifts(ds: Dataset) -> None:
    ds.shifts["A"] = Shift(id="A", name="Shift A", start_minute=480, end_minute=960)
    ds.shifts["B"] = Shift(id="B", name="Shift B", start_minute=960, end_minute=1440)


def _build_calendar(ds: Dataset) -> None:
    for d in range(N_DAYS):
        dow = d % 7
        if dow == 6 or d == EXTRA_HOLIDAY_DAY:
            ds.calendar.append(CalendarDay(day_index=d, is_working=False))
        elif dow == 5:  # Saturday: morning shift only
            ds.calendar.append(CalendarDay(day_index=d, is_working=True, shift_ids=["A"]))
        else:  # Monday-Friday: two shifts
            ds.calendar.append(CalendarDay(day_index=d, is_working=True, shift_ids=["A", "B"]))


def _build_skills(ds: Dataset) -> None:
    for sid, name in SKILLS.items():
        ds.skills[sid] = Skill(id=sid, name=name)


def _build_materials(ds: Dataset) -> None:
    for mid, name, unit in MATERIALS:
        ds.materials[mid] = Material(id=mid, name=name, unit=unit)


def _build_inventory(ds: Dataset) -> None:
    for mid, on_hand in INVENTORY:
        ds.inventory[mid] = MaterialInventory(material_id=mid, on_hand=on_hand)


def _build_boms(ds: Dataset) -> None:
    for pid, items in BOMS.items():
        ds.boms[pid] = BOM(
            product_id=pid,
            items=[BomItem(material_id=mid, quantity_per_unit=qty)
                   for mid, qty in items],
        )


def _build_employees(ds: Dataset) -> None:
    for eid, name, shift_ids, skill_ids, wc_ids, a_from, a_until in EMPLOYEES:
        ds.employees[eid] = Employee(
            id=eid,
            name=name,
            shift_ids=list(shift_ids),
            skill_ids=list(skill_ids),
            work_center_ids=list(wc_ids),
            available_from=a_from,
            available_until=a_until or ds.meta["horizon_end"],
        )


def _cover_order_book(ds: Dataset) -> None:
    """Raise on-hand inventory to exactly cover the whole order book.

    Aggregates every order's material demand via ``material_requirements``
    and sets each material's on-hand quantity to that total. BOMs, products,
    orders, and all scheduling data are unchanged; only inventory changes.
    Deterministic and never consumes, reserves, or allocates stock.
    """
    demand: Dict[str, float] = {}
    for order in ds.orders.values():
        for mid, qty in ds.material_requirements(order.product_id, order.quantity).items():
            demand[mid] = demand.get(mid, 0.0) + qty
    for mid, req in demand.items():
        ds.inventory[mid] = MaterialInventory(material_id=mid, on_hand=req)


def generate_dataset(n_orders: int = N_ORDERS, seed: int = SEED,
                     material_feasible: bool = False) -> Dataset:
    """Build the deterministic Phase 3 dataset.

    When ``material_feasible`` is True, on-hand inventory is raised to exactly
    cover the entire order book's aggregated demand so the dataset is
    material-feasible; everything else stays identical to the default.
    """
    rng = random.Random(seed)
    ds = Dataset()
    ds.meta["seed"] = seed
    ds.meta["n_orders"] = n_orders
    ds.meta["material_feasible"] = material_feasible
    ds.meta["horizon_end"] = N_DAYS * DAY_MINUTES

    # work centers + machines
    for wc_id, (name, machine_ids) in WORK_CENTERS.items():
        wc = WorkCenter(id=wc_id, name=name, machine_ids=list(machine_ids))
        ds.work_centers[wc_id] = wc
        for mid in machine_ids:
            ds.machines[mid] = Machine(id=mid, name=mid, work_center_id=wc_id)

    # factory calendar + availability windows
    _build_shifts(ds)
    _build_calendar(ds)
    ds.maintenance = [MaintenanceWindow(machine_id=m, start=s, end=e) for m, s, e in MAINTENANCE]
    ds.downtime = [DowntimeWindow(machine_id=m, start=s, end=e) for m, s, e in DOWNTIME]

    # skills + employees
    _build_skills(ds)
    _build_employees(ds)

    # materials + inventory (Phase 4.2)
    _build_materials(ds)
    _build_inventory(ds)

    # products
    product_ids = list(PRODUCTS.keys())
    for pid in product_ids:
        ds.products[pid] = Product(id=pid, name=pid)

    # BOMs (Phase 4.3): reference data only - Product -> BOM -> Material
    _build_boms(ds)

    # orders: first build records, then assign release/due times. Orders with
    # longer routings get the latest release slots so their chains spill across
    # the shift boundary (the calendar genuinely binds).
    records: List[Tuple[str, int, int, int]] = []
    for i in range(n_orders):
        pid = product_ids[i % len(product_ids)]
        quantity = 10 + rng.randint(0, 30)
        priority = 3 if rng.random() < 0.3 else (2 if rng.random() < 0.6 else 1)
        total_proc = sum(
            int(round(base + per_unit * quantity))
            for step in PRODUCTS[pid]
            for base, per_unit in [STEPS[step][1:]]
        )
        records.append((pid, quantity, priority, total_proc))

    op_counts = {pid: len(PRODUCTS[pid]) for pid in product_ids}
    rank = sorted(range(n_orders), key=lambda i: (-op_counts[records[i][0]], i))

    orders: List[Order] = []
    for idx, i in enumerate(rank):
        pid, quantity, priority, total_proc = records[i]
        slot = idx % 5
        release = 480 + slot * 180 + rng.randint(0, 120)  # spread across Monday
        due = release + total_proc + DUE_SLACK[priority]
        orders.append(Order(id=f"ORD{i:03d}", product_id=pid, quantity=quantity,
                            release_time=release, due_time=due, priority=priority))
    ds.orders = {o.id: o for o in orders}

    # Phase 4.7 Part 2: scale inventory to cover the order book when requested
    if material_feasible:
        _cover_order_book(ds)

    # operations (per order) + per-order routing
    seq_counter = 0
    for o in orders:
        steps = PRODUCTS[o.product_id]
        op_ids: List[str] = []
        for k, step in enumerate(steps):
            wc_id, base, per_unit = STEPS[step]
            processing = int(round(base + per_unit * o.quantity))
            seq_counter += 1
            op = Operation(
                id=f"O{seq_counter:04d}",
                order_id=o.id,
                sequence=k,
                work_center_id=wc_id,
                processing_time=processing,
                setup_time=SETUP_TIMES[STEP_SKILL[step]],
                allowed_machine_ids=list(ds.work_centers[wc_id].machine_ids),
                required_skill_id=STEP_SKILL[step],
                employee_required=True,
            )
            # one single-machine operation for variety (DESK assembly on ASM-1)
            if o.product_id == "P_DESK" and step == "ASM":
                op.allowed_machine_ids = ["ASM-1"]
            ds.operations[op.id] = op
            op_ids.append(op.id)
        ds.routings[o.id] = Routing(product_id=o.product_id, operations=op_ids)

    ds.meta["n_operations"] = len(ds.operations)
    ds.meta["n_machines"] = len(ds.machines)
    ds.meta["n_work_centers"] = len(ds.work_centers)
    ds.meta["n_skills"] = len(ds.skills)
    ds.meta["n_employees"] = len(ds.employees)
    ds.meta["n_days"] = N_DAYS
    ds.meta["n_shifts"] = len(ds.shifts)
    ds.meta["n_holidays"] = sum(1 for d in ds.calendar if not d.is_working)
    ds.meta["n_maintenance"] = len(ds.maintenance)
    ds.meta["n_downtime"] = len(ds.downtime)
    ds.meta["n_setup"] = sum(1 for op in ds.operations.values() if op.setup_time > 0)
    ds.meta["n_materials"] = len(ds.materials)
    ds.meta["n_inventory"] = len(ds.inventory)
    ds.meta["n_boms"] = len(ds.boms)
    ds.meta["n_bom_items"] = sum(len(bom.items) for bom in ds.boms.values())
    return ds


def generate_infeasible_dataset() -> Dataset:
    """Deterministic infeasible dataset (Phase 4, CLI diagnostics demo/E2E).

    A single operation requires a CUTTING-qualified employee, but the only
    qualified employee works Shift B while the calendar offers Shift A only,
    so no employee can ever be assigned. All local checks pass structurally;
    the model is infeasible and is diagnosed as EMPLOYEE_SHORTAGE.
    """
    ds = Dataset()
    ds.meta["seed"] = SEED
    ds.meta["n_orders"] = 1
    ds.meta["n_operations"] = 1
    ds.meta["n_machines"] = 1
    ds.meta["n_work_centers"] = 1
    ds.meta["n_skills"] = 1
    ds.meta["n_employees"] = 1
    ds.meta["n_days"] = 1
    ds.meta["n_shifts"] = 2
    ds.meta["n_holidays"] = 0
    ds.meta["n_maintenance"] = 0
    ds.meta["n_downtime"] = 0
    ds.meta["horizon_end"] = DAY_MINUTES

    ds.shifts["A"] = Shift(id="A", name="Shift A", start_minute=480, end_minute=960)
    ds.shifts["B"] = Shift(id="B", name="Shift B", start_minute=960, end_minute=1440)
    ds.calendar = [CalendarDay(day_index=0, is_working=True, shift_ids=["A"])]

    ds.work_centers["WC_CUTTING"] = WorkCenter(
        id="WC_CUTTING", name="Cutting", machine_ids=["CUT-1"])
    ds.machines["CUT-1"] = Machine(id="CUT-1", name="CUT-1",
                                   work_center_id="WC_CUTTING")
    ds.skills["CUTTING"] = Skill(id="CUTTING", name="Cutting")
    ds.employees["E_CUT_B"] = Employee(
        id="E_CUT_B", name="Cutting B", shift_ids=["B"],
        skill_ids=["CUTTING"], work_center_ids=["WC_CUTTING"],
        available_from=0, available_until=DAY_MINUTES)

    ds.orders["ORD000"] = Order(id="ORD000", product_id="P1", quantity=1,
                                release_time=480, due_time=1000, priority=1)
    ds.operations["O0001"] = Operation(
        id="O0001", order_id="ORD000", sequence=0, work_center_id="WC_CUTTING",
        processing_time=60, allowed_machine_ids=["CUT-1"],
        required_skill_id="CUTTING", employee_required=True)
    ds.routings["ORD000"] = Routing(product_id="P1", operations=["O0001"])
    return ds
