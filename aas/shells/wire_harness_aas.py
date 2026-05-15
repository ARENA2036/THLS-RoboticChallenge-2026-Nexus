"""
WireHarnessAAS — Product AAS for a CDM WireHarness.

Carries three submodels:
  1. DigitalNameplate   (IDTA 02006-2-0)
  2. HierarchicalBOM    (IDTA 02011-1-1)
  3. CDMTopology        (urn:NEXUS:submodel:CDMTopology:1-0)

GlobalAssetId convention:
    urn:NEXUS:harness:{part_number}:{harness_id}
"""

from dataclasses import dataclass, field

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.hierarchical_bom import build_hierarchical_bom
from ..submodels.cdm_topology import build_cdm_topology


@dataclass
class WireHarnessAASBundle:
    """A complete WireHarnessAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    bom_submodel: model.Submodel
    topology_submodel: model.Submodel

    def all_objects(self) -> list:
        return [
            self.shell,
            self.nameplate_submodel,
            self.bom_submodel,
            self.topology_submodel,
        ]


def build_wire_harness_aas(harness, component_asset_ids: dict) -> WireHarnessAASBundle:
    """Build a complete WireHarnessAAS from a CDM WireHarness.

    Args:
        harness: CDM WireHarness instance.
        component_asset_ids: Dict {f"{type_token}:{part_number}" → GlobalAssetId}
            for all ComponentAAS shells built from the same harness.  Used to
            populate SameAs references in the BOM submodel.

    Returns:
        WireHarnessAASBundle with shell and three submodels.
    """
    safe_pn = harness.part_number.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:harness:{safe_pn}:{harness.id}"

    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    bom_id = f"{global_asset_id}/submodel/HierarchicalBOM"
    topology_id = f"{global_asset_id}/submodel/CDMTopology"

    # --- DigitalNameplate ---
    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=harness.company_name,
        manufacturer_part_number=harness.part_number,
        manufacturer_product_designation=harness.description,
        manufacturer_product_family="WireHarness",
        software_version=harness.version,
        date_of_manufacture=harness.created_at,
    )

    # --- HierarchicalBOM ---
    bom = build_hierarchical_bom(bom_id, harness, component_asset_ids)

    # --- CDMTopology ---
    topology = build_cdm_topology(topology_id, harness)

    # --- Shell ---
    asset_info = model.AssetInformation(
        model.AssetKind.INSTANCE,
        global_asset_id=global_asset_id,
    )

    def _sm_ref(sm: model.Submodel) -> model.ModelReference:
        return model.ModelReference(
            (model.Key(model.KeyTypes.SUBMODEL, sm.id),),
            model.Submodel,
        )

    shell = model.AssetAdministrationShell(
        asset_information=asset_info,
        id_=f"{global_asset_id}/shell",
        submodel={_sm_ref(nameplate), _sm_ref(bom), _sm_ref(topology)},
    )

    return WireHarnessAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        bom_submodel=bom,
        topology_submodel=topology,
    )
