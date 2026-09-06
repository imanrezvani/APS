"""Phase 8 Dataset JSON persistence.

``dataset_to_json`` serializes a :class:`~aps_engine.models.domain.Dataset`
into a JSON document and ``dataset_from_json`` rebuilds it losslessly. The
round trip preserves the complete domain object graph: products, orders,
operations, routings, work centers, machines, skills, employees, shifts,
calendar, maintenance/downtime windows, the sequence-dependent setup
matrix, materials, BOMs and inventory, plus the free-form ``meta`` dict.

Serialization notes
-------------------
* Every entity dataclass is stored via ``dataclasses.asdict`` and rebuilt
  from its own JSON object by constructor keyword, so no domain dataclass
  needs to change.
* ``Dataset.setup_matrix`` is keyed by ``(from_family, to_family)`` tuples,
  which JSON cannot represent directly. Keys are encoded as explicit
  ``[from, to, minutes]`` triples (a plain array, immune to any delimiter
  collision inside family ids) and restored to the tuple-keyed dict. The
  triples are emitted in sorted key order so output is deterministic.
* The document carries a top-level ``"format"`` tag so a future schema
  change can be detected and migrated explicitly.
"""

from dataclasses import asdict
from json import dumps, loads
from typing import Any, Dict, List, Optional, Type

from aps_engine.models.domain import (
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

FORMAT = "aps-engine.dataset.v1"

# Dataset fields that map {entity id -> entity}, in declaration order.
_DICT_COLLECTIONS: List = [
    ("products", Product),
    ("orders", Order),
    ("operations", Operation),
    ("routings", Routing),
    ("work_centers", WorkCenter),
    ("machines", Machine),
    ("skills", Skill),
    ("employees", Employee),
    ("shifts", Shift),
    ("materials", Material),
    ("boms", BOM),
    ("inventory", MaterialInventory),
]

# Dataset fields that map to a plain list of entities.
_LIST_COLLECTIONS: List = [
    ("calendar", CalendarDay),
    ("maintenance", MaintenanceWindow),
    ("downtime", DowntimeWindow),
]


def _restore_entity(entity_cls: Type, payload: Dict[str, Any]) -> Any:
    """Rebuild one entity from its ``asdict`` payload.

    Only ``BOM`` nests further dataclasses (its ``items`` are ``BomItem``
    objects); every other entity is rebuilt directly from its keyword
    arguments.
    """
    if entity_cls is BOM:
        items = payload.get("items") or []
        rebuilt = dict(payload)
        rebuilt["items"] = [BomItem(**item) for item in items]
        return BOM(**rebuilt)
    return entity_cls(**payload)


def dataset_to_json(dataset: Dataset) -> str:
    """Serialize ``dataset`` to a JSON string.

    The returned text is a complete, lossless encoding of the Dataset. Use
    ``dataset_from_json`` (or the equivalent ``json.loads``-then-rebuild
    path) to reconstruct an exactly equal Dataset.
    """
    document = _document(dataset)
    return dumps(document)


def dataset_from_json(data: Any) -> Dataset:
    """Rebuild a Dataset from a JSON string or a parsed JSON document.

    Accepts either the raw text produced by ``dataset_to_json`` or the
    already-decoded dict (e.g. from ``json.load``). Raises ``ValueError``
    when the document does not carry the expected ``format`` tag.
    """
    if isinstance(data, str):
        document = loads(data)
    elif isinstance(data, dict):
        document = data
    else:
        raise ValueError(
            "dataset_from_json expects a JSON string or a parsed JSON dict, "
            f"got {type(data).__name__}"
        )
    return _parse(document)


def _document(dataset: Dataset) -> Dict[str, Any]:
    """Encode the Dataset as a JSON-safe document (dict/list/scalar)."""
    doc: Dict[str, Any] = {"format": FORMAT, "meta": dict(dataset.meta)}

    for field_name, entity_cls in _DICT_COLLECTIONS:
        collection = getattr(dataset, field_name)
        doc[field_name] = {eid: asdict(entity) for eid, entity in collection.items()}

    for field_name, entity_cls in _LIST_COLLECTIONS:
        collection = getattr(dataset, field_name)
        doc[field_name] = [asdict(entity) for entity in collection]

    doc["setup_matrix"] = [
        [from_family, to_family, minutes]
        for (from_family, to_family), minutes in sorted(dataset.setup_matrix.items())
    ]
    return doc


def _parse(document: Dict[str, Any]) -> Dataset:
    """Decode a JSON-safe document back into a Dataset."""
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(
            f"unsupported dataset document (expected format {FORMAT!r})"
        )

    dataset = Dataset(meta=dict(document.get("meta") or {}))

    for field_name, entity_cls in _DICT_COLLECTIONS:
        raw = document.get(field_name) or {}
        setattr(
            dataset,
            field_name,
            {eid: _restore_entity(entity_cls, payload) for eid, payload in raw.items()},
        )

    for field_name, entity_cls in _LIST_COLLECTIONS:
        raw = document.get(field_name) or []
        setattr(
            dataset,
            field_name,
            [_restore_entity(entity_cls, payload) for payload in raw],
        )

    dataset.setup_matrix = _parse_setup_matrix(document.get("setup_matrix"))
    return dataset


def _parse_setup_matrix(raw: Any) -> Dict:
    """Decode the serialized ``[from, to, minutes]`` triples.

    Returns an empty matrix when the field is absent; raises ``ValueError``
    on malformed entries.
    """
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ValueError(f"setup_matrix must be a list, got {type(raw).__name__}")
    matrix: Dict = {}
    for entry in raw:
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], str)
        ):
            raise ValueError(f"malformed setup_matrix entry: {entry!r}")
        matrix[(entry[0], entry[1])] = int(entry[2])
    return matrix
