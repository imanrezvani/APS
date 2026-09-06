"""Phase 8 IO layer: JSON serialization of domain entities and solve outputs."""

from aps_engine.io.dataset_io import dataset_from_json, dataset_to_json
from aps_engine.io.result_io import (
    load_result,
    result_from_json,
    result_to_json,
    save_result,
)

__all__ = [
    "dataset_from_json",
    "dataset_to_json",
    "load_result",
    "result_from_json",
    "result_to_json",
    "save_result",
]
