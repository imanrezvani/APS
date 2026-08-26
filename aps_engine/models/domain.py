"""Phase 6 domain model: production scheduling entities.

Object graph:
  Order  -> product_id (Product)
  Product -> Routing (ordered list of Operation ids), BOM (bill of materials)
  Operation -> work_center_id (WorkCenter), allowed_machine_ids ([Machine]),
               required_skill_id (Skill), employee_required (bool),
               setup_time (int, machine changeover before the operation),
               setup_family_id (str, changeover family; "" = none)
  WorkCenter -> machine_ids ([Machine])
  Employee -> skill_ids ([Skill]), work_center_ids ([WorkCenter]),
              shift_ids ([Shift]), available_from/until
  BOM -> product_id (Product), items ([BomItem])
  BomItem -> material_id (Material), quantity_per_unit (units of the material
             consumed per unit of the product)
  Material -> id, name, unit
  MaterialInventory -> material_id (Material), on_hand (current on-hand
             quantity in the material's unit)
  MaterialFeasibility -> feasible, requirements ({material: required}),
             availability ({material: on_hand}), shortages ({material: short})
  Dataset -> setup_matrix ({(from_family, to_family): minutes}, a global
             sequence-dependent changeover matrix; empty = sequence-independent),
             materials ({id: Material}), boms ({product_id: BOM}),
             inventory ({material_id: MaterialInventory})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class Product:
    id: str
    name: str


@dataclass
class Order:
    id: str
    product_id: str
    quantity: int
    release_time: int
    due_time: int
    priority: int = 1


@dataclass
class Operation:
    id: str
    order_id: str
    sequence: int
    work_center_id: str
    processing_time: int
    setup_time: int = 0
    setup_family_id: str = ""
    allowed_machine_ids: List[str] = field(default_factory=list)
    required_skill_id: str = ""
    employee_required: bool = False


@dataclass
class WorkCenter:
    id: str
    name: str
    machine_ids: List[str] = field(default_factory=list)


@dataclass
class Machine:
    id: str
    name: str
    work_center_id: str


@dataclass
class Skill:
    id: str
    name: str


@dataclass
class Employee:
    id: str
    name: str
    shift_ids: List[str] = field(default_factory=list)
    skill_ids: List[str] = field(default_factory=list)
    work_center_ids: List[str] = field(default_factory=list)
    available_from: int = 0
    available_until: int = 0


@dataclass
class Shift:
    id: str
    name: str
    start_minute: int  # minutes since midnight, within a single day
    end_minute: int    # minutes since midnight


@dataclass
class CalendarDay:
    day_index: int
    is_working: bool
    shift_ids: List[str] = field(default_factory=list)


@dataclass
class MaintenanceWindow:
    machine_id: str
    start: int  # absolute minutes
    end: int    # absolute minutes
    reason: str = "maintenance"


@dataclass
class DowntimeWindow:
    machine_id: str
    start: int  # absolute minutes
    end: int    # absolute minutes
    reason: str = "downtime"


@dataclass
class Material:
    id: str
    name: str
    unit: str = "unit"


@dataclass
class BomItem:
    material_id: str
    quantity_per_unit: float = 1.0


@dataclass
class BOM:
    product_id: str
    items: List[BomItem] = field(default_factory=list)


@dataclass
class MaterialInventory:
    material_id: str
    on_hand: float = 0.0


@dataclass
class MaterialFeasibility:
    """Read-only material feasibility of a production quantity.

    ``requirements`` maps each required material to its needed quantity,
    ``availability`` maps the same materials to their current on-hand
    inventory (0.0 when no inventory record exists), ``shortages`` contains
    only the materials whose requirement exceeds availability, and
    ``feasible`` is True exactly when there are no shortages.
    """
    feasible: bool
    requirements: Dict[str, float] = field(default_factory=dict)
    availability: Dict[str, float] = field(default_factory=dict)
    shortages: Dict[str, float] = field(default_factory=dict)


@dataclass
class Routing:
    product_id: str
    operations: List[str] = field(default_factory=list)


@dataclass
class Dataset:
    meta: Dict[str, Any] = field(default_factory=dict)
    products: Dict[str, Product] = field(default_factory=dict)
    orders: Dict[str, Order] = field(default_factory=dict)
    operations: Dict[str, Operation] = field(default_factory=dict)
    routings: Dict[str, Routing] = field(default_factory=dict)
    work_centers: Dict[str, WorkCenter] = field(default_factory=dict)
    machines: Dict[str, Machine] = field(default_factory=dict)
    skills: Dict[str, Skill] = field(default_factory=dict)
    employees: Dict[str, Employee] = field(default_factory=dict)
    shifts: Dict[str, Shift] = field(default_factory=dict)
    calendar: List[CalendarDay] = field(default_factory=list)
    maintenance: List[MaintenanceWindow] = field(default_factory=list)
    downtime: List[DowntimeWindow] = field(default_factory=list)
    setup_matrix: Dict[Tuple[str, str], int] = field(default_factory=dict)
    materials: Dict[str, Material] = field(default_factory=dict)
    boms: Dict[str, BOM] = field(default_factory=dict)
    inventory: Dict[str, MaterialInventory] = field(default_factory=dict)

    def operations_of_order(self, order_id: str) -> List[Operation]:
        return [self.operations[i] for i in self.routings[order_id].operations]

    def bom_for(self, product_id: str) -> Optional[BOM]:
        """The bill of materials for a product, or None when absent."""
        return self.boms.get(product_id)

    def materials_for(self, product_id: str) -> List[BomItem]:
        """The material requirements of a product's BOM (empty when absent)."""
        bom = self.bom_for(product_id)
        return bom.items if bom is not None else []

    def inventory_of(self, material_id: str) -> Optional[MaterialInventory]:
        """The inventory record for a material, or None when absent."""
        return self.inventory.get(material_id)

    def material_requirements(self, product_id: str, quantity: float) -> Dict[str, float]:
        """Aggregated material requirements for producing ``quantity`` units.

        Each BOM item's ``quantity_per_unit`` is multiplied by ``quantity``;
        when the same material appears more than once in the BOM the amounts
        are summed. Returns ``{}`` for a product without a BOM and for
        ``quantity == 0``; raises ``ValueError`` for a negative quantity.

        This is a pure requirements calculation: it neither enforces
        inventory availability nor reserves or consumes any stock.
        """
        if quantity < 0:
            raise ValueError(f"quantity must be >= 0, got {quantity}")
        requirements: Dict[str, float] = {}
        if quantity == 0:
            return requirements
        for item in self.materials_for(product_id):
            requirements[item.material_id] = (
                requirements.get(item.material_id, 0.0) + item.quantity_per_unit * quantity)
        return requirements

    def material_availability(self, product_id: str, quantity: float) -> Dict[str, float]:
        """Shortage per required material for producing ``quantity`` units.

        For every material required by the product's BOM, returns the amount
        by which the on-hand inventory falls short of the requirement; 0.0
        means the material is sufficient. A material with no inventory record
        is treated as having no stock (full shortage). Returns ``{}`` for a
        product without a BOM and for ``quantity == 0``; raises ``ValueError``
        for a negative quantity (mirroring ``material_requirements``).

        This is an availability check only: it never consumes, reserves, or
        allocates inventory.
        """
        shortages: Dict[str, float] = {}
        for mid, required in self.material_requirements(product_id, quantity).items():
            record = self.inventory_of(mid)
            on_hand = record.on_hand if record is not None else 0.0
            shortages[mid] = max(0.0, required - on_hand)
        return shortages

    def material_feasibility(self, product_id: str, quantity: float) -> MaterialFeasibility:
        """Read-only material feasibility of a production quantity.

        Composes ``material_requirements`` and ``material_availability`` into
        a single result: required per-material quantities, current on-hand
        inventory per material, the shortage per short material, and an
        overall ``feasible`` flag (True when there are no shortages). A
        material with no inventory record counts as having zero stock.

        Raises ``ValueError`` for a negative quantity and never consumes,
        reserves, or allocates inventory.
        """
        requirements = self.material_requirements(product_id, quantity)
        availability: Dict[str, float] = {}
        for mid in requirements:
            record = self.inventory_of(mid)
            availability[mid] = record.on_hand if record is not None else 0.0
        shortages = {
            mid: short for mid, short in self.material_availability(product_id, quantity).items()
            if short > 0.0
        }
        return MaterialFeasibility(
            feasible=not shortages,
            requirements=requirements,
            availability=availability,
            shortages=shortages,
        )

    def order_material_feasibility(self, order_id: str) -> MaterialFeasibility:
        """Read-only material feasibility of a production order.

        Resolves the order's product and quantity and delegates to
        ``material_feasibility``, so BOM and inventory logic is not
        duplicated. Raises ``KeyError`` for an unknown ``order_id`` and
        ``ValueError`` for an order with a negative quantity. Never consumes,
        reserves, or allocates inventory.
        """
        order = self.orders[order_id]
        return self.material_feasibility(order.product_id, order.quantity)

    def order_book_material_feasibility(self) -> MaterialFeasibility:
        """Read-only material feasibility of the entire production order book.

        Aggregates the material requirements of every order (each order's
        product x quantity via ``material_requirements``), compares the
        totals against current inventory, and reports the shortage per short
        material. Feasible only when no material is short; a material with no
        inventory record counts as zero stock. An empty order book, or one
        whose total demand is zero, is feasible with empty requirements.
        Deterministic and never consumes, reserves, or allocates inventory.
        """
        requirements: Dict[str, float] = {}
        for order in self.orders.values():
            for mid, qty in self.material_requirements(order.product_id, order.quantity).items():
                requirements[mid] = requirements.get(mid, 0.0) + qty

        availability: Dict[str, float] = {}
        for mid in requirements:
            record = self.inventory_of(mid)
            availability[mid] = record.on_hand if record is not None else 0.0

        shortages = {
            mid: max(0.0, requirements[mid] - availability[mid])
            for mid in requirements
            if requirements[mid] > availability[mid]
        }
        return MaterialFeasibility(
            feasible=not shortages,
            requirements=requirements,
            availability=availability,
            shortages=shortages,
        )

    def material_demand(self, order_id: str) -> Dict[str, float]:
        """Aggregated material demand of a single production order.

        Resolves the order's product and quantity and delegates to
        ``material_requirements``, so BOM logic is not duplicated. When the
        same material appears more than once in the BOM the amounts are summed
        within the order. Raises ``KeyError`` for an unknown ``order_id`` and
        ``ValueError`` for an order with a negative quantity (existing
        conventions). Deterministic and never consumes, reserves, or allocates
        inventory.
        """
        order = self.orders[order_id]
        return self.material_requirements(order.product_id, order.quantity)

    def material_demands(self) -> Dict[str, Dict[str, float]]:
        """Aggregated material demand of every production order.

        Maps each order id to that order's material demand (via
        ``material_demand``), following the deterministic insertion order of
        ``self.orders``. Shared materials are aggregated within each order.
        Never consumes, reserves, or allocates inventory.
        """
        return {order_id: self.material_demand(order_id) for order_id in self.orders}


def changeover(ds: Dataset,
               prev: Union["Operation", "MaintenanceWindow", "DowntimeWindow"],
               nxt: Union["Operation", "MaintenanceWindow", "DowntimeWindow"]) -> int:
    """Required changeover gap (minutes) between two consecutive activities
    that run on the same machine, where ``prev`` runs immediately before
    ``nxt``.

    This single function is the source of truth shared by the CP-SAT capacity
    model, the post-solve validator and the CLI setup summary.

    operation -> operation:
        the family matrix value ``setup_matrix[(f_prev, f_nxt)]`` when the
        dataset defines a setup matrix AND both operations carry a non-empty
        ``setup_family_id``, otherwise the following operation's ``setup_time``
        (Phase 5 sequence-independent setup). A missing matrix entry also
        falls back to ``nxt.setup_time``.

    any activity -> maintenance/downtime window:
        0 (no setup before a machine break).

    maintenance/downtime window -> operation:
        the operation's ``setup_time`` (the machine must be set up again after
        a break; identical to Phase 5).

    When a break lies between two operations, the solver enforces the
    operation-to-operation changeover and the post-break setup as two
    independent lower bounds, so the stronger of the two binds - the gaps are
    never summed.
    """
    if isinstance(nxt, (MaintenanceWindow, DowntimeWindow)):
        return 0
    if not isinstance(prev, Operation):
        return nxt.setup_time
    if ds.setup_matrix and prev.setup_family_id and nxt.setup_family_id:
        return ds.setup_matrix.get(
            (prev.setup_family_id, nxt.setup_family_id), nxt.setup_time)
    return nxt.setup_time
