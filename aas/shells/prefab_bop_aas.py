"""
PreFabBillOfProcessAAS — Process AAS for upstream wire pre-fabrication steps.

Carries two submodels:
  1. DigitalNameplate         (IDTA 02006-2-0)
  2. PreFabBillOfProcess      (urn:NEXUS:submodel:PreFabBillOfProcess:1-0)

GlobalAssetId convention:
    urn:NEXUS:prefab:{harness_id}
"""

from dataclasses import dataclass

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.prefab_process_parameters import build_prefab_process_parameters


@dataclass
class PreFabBoPAASBundle:
    """A complete PreFabBillOfProcessAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    prefab_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.prefab_submodel]


def build_prefab_bop_aas(
    harness,
    strip_length_mm: float = 8.0,
    default_crimp_force_n: float = 500.0,
    manufacturer_name: str = "NEXUS",
) -> PreFabBoPAASBundle:
    """Build a complete PreFabBillOfProcessAAS from a WireHarness.

    Generates Cut → Strip → Crimp process phases following OPC 40570.

    Args:
        harness: WireHarness CDM instance.
        strip_length_mm: Default insulation strip length in mm.
        default_crimp_force_n: Default crimp force in Newtons.
        manufacturer_name: Organisation performing pre-fabrication.

    Returns:
        PreFabBoPAASBundle with shell and two submodels.
    """
    safe_id = harness.id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:prefab:{safe_id}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    prefab_id = f"{global_asset_id}/submodel/PreFabBillOfProcess"

    n_wires = len(harness.wire_occurrences or [])

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=harness.part_number or harness.id,
        manufacturer_product_designation=(
            f"Pre-fabrication BoP for harness {harness.id}: "
            f"{n_wires} wire occurrences (Cut/Strip/Crimp, OPC 40570)"
        ),
        manufacturer_product_family="PreFabBillOfProcess",
        manufacturer_product_type="WirePreFabrication",
    )

    prefab_sm = build_prefab_process_parameters(
        prefab_id,
        harness,
        strip_length_mm=strip_length_mm,
        default_crimp_force_n=default_crimp_force_n,
    )

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
        submodel={_sm_ref(nameplate), _sm_ref(prefab_sm)},
    )

    return PreFabBoPAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        prefab_submodel=prefab_sm,
    )
