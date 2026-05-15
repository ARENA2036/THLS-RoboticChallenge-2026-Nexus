"""
AAS JSON serializer.

Thin wrapper around basyx.aas.adapter.json that bundles all AAS objects
from one or more bundles into a DictObjectStore and writes them to JSON files.

Output format: IDTA-compliant AAS Part 2 JSON
  {"assetAdministrationShells": [...], "submodels": [...]}
"""

import json
from pathlib import Path
from typing import Iterable, Union

import basyx.aas.model as model
import basyx.aas.adapter.json as aas_json


def write_aas_json(
    output_path: Union[str, Path],
    *bundles,
    extra_objects: Iterable = (),
) -> model.DictObjectStore:
    """Serialize one or more AAS bundles to a single JSON file.

    Args:
        output_path: Destination file path (will be created or overwritten).
        *bundles: Any AAS bundle objects that implement .all_objects() returning
            a list of basyx Identifiable objects (shells + submodels).
        extra_objects: Optional additional basyx Identifiable objects to include.

    Example:
        write_aas_json(
            "output/wire_harness.json",
            wire_harness_bundle,
            *component_bundles,
        )
    """
    all_objects: list = []
    for bundle in bundles:
        all_objects.extend(bundle.all_objects())
    all_objects.extend(extra_objects)

    store = model.DictObjectStore(all_objects)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        aas_json.write_aas_json_file(f, store)

    return store


def read_aas_json(
    input_path: Union[str, Path],
    failsafe: bool = False,
) -> model.DictObjectStore:
    """Read an AAS JSON file back into a DictObjectStore.

    Args:
        input_path: Path to an IDTA-compliant AAS JSON file.
        failsafe: If True, log and skip malformed objects instead of raising.

    Returns:
        DictObjectStore containing all deserialized shells and submodels.
    """
    with open(input_path, encoding="utf-8") as f:
        return aas_json.read_aas_json_file(f, failsafe=failsafe)


def summarize_store(store: model.DictObjectStore) -> dict:
    """Return a summary dict with shell and submodel counts for quick verification."""
    shells = [o for o in store if isinstance(o, model.AssetAdministrationShell)]
    submodels = [o for o in store if isinstance(o, model.Submodel)]
    return {
        "total_objects": len(list(store)),
        "shells": len(shells),
        "submodels": len(submodels),
        "shell_ids": [s.id for s in shells],
        "submodel_ids": [sm.id for sm in submodels],
    }
