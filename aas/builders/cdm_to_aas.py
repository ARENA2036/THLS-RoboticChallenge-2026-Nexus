"""
CDM → AAS builder.

Converts a CDM WireHarness into a complete set of AAS objects:
  - One WireHarnessAAS (product shell + 3 submodels)
  - N ComponentAAS shells (one per unique component definition across all
    Connector, Wire, Terminal, WireProtection, Accessory, Fixing types)

Usage:
    from aas.builders.cdm_to_aas import build_aas_from_harness
    result = build_aas_from_harness(harness)
    # result.wire_harness_bundle.all_objects() + all component objects
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict

# Make CDM importable when running from project root
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from public.cdm.definitions.cdm_schema import WireHarness

from ..shells.component_aas import build_component_aas, ComponentAASBundle
from ..shells.wire_harness_aas import build_wire_harness_aas, WireHarnessAASBundle


@dataclass
class CDMToAASResult:
    """Full AAS output for one WireHarness."""
    wire_harness_bundle: WireHarnessAASBundle
    component_bundles: List[ComponentAASBundle] = field(default_factory=list)

    def all_objects(self) -> list:
        """Return every AAS identifiable object (shells + submodels)."""
        objects = list(self.wire_harness_bundle.all_objects())
        for bundle in self.component_bundles:
            objects.extend(bundle.all_objects())
        return objects


def build_aas_from_harness(harness: WireHarness) -> CDMToAASResult:
    """Build the complete AAS representation of a CDM WireHarness.

    Deduplicates component definitions by part_number so each unique part
    gets exactly one ComponentAAS, even if used multiple times.

    Args:
        harness: A fully populated CDM WireHarness instance.

    Returns:
        CDMToAASResult containing the WireHarnessAAS and all ComponentAAS bundles.
    """
    # --- Step 1: Build ComponentAAS for each unique component definition ---
    component_bundles: List[ComponentAASBundle] = []
    # Maps f"{type_token}:{part_number}" → GlobalAssetId (for BOM SameAs refs)
    component_asset_ids: Dict[str, str] = {}

    seen_keys: set = set()

    component_groups = [
        ("connector", harness.connectors),
        ("wire", harness.wires),
        ("terminal", harness.terminals),
        ("wire_protection", harness.wire_protections),
        ("accessory", harness.accessories),
        ("fixing", harness.fixings),
    ]

    for type_token, components in component_groups:
        for component in components:
            safe_pn = component.part_number.replace(" ", "_").replace("/", "_")
            key = f"{type_token}:{safe_pn}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            bundle = build_component_aas(component)
            component_bundles.append(bundle)
            component_asset_ids[key] = bundle.shell.asset_information.global_asset_id

    # --- Step 2: Build WireHarnessAAS (uses component IDs for BOM SameAs) ---
    wire_harness_bundle = build_wire_harness_aas(harness, component_asset_ids)

    return CDMToAASResult(
        wire_harness_bundle=wire_harness_bundle,
        component_bundles=component_bundles,
    )
