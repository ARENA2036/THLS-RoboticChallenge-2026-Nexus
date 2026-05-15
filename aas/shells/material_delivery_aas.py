"""
MaterialDeliveryAAS — Resource AAS for the material staging/pickup configuration.

Carries two submodels:
  1. DigitalNameplate    (IDTA 02006-2-0)
  2. MaterialDelivery    (urn:NEXUS:submodel:MaterialDelivery:1-0)

GlobalAssetId convention:
    urn:NEXUS:delivery:{station_id}
"""

from dataclasses import dataclass

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.material_delivery import build_material_delivery


@dataclass
class MaterialDeliveryAASBundle:
    """A complete MaterialDeliveryAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    delivery_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.delivery_submodel]


def build_material_delivery_aas(
    station_id: str,
    board_setup_config=None,
    wire_routing_config=None,
    manufacturer_name: str = "NEXUS",
) -> MaterialDeliveryAASBundle:
    """Build a complete MaterialDeliveryAAS from simulation config objects.

    Args:
        station_id: Station identifier (used in GlobalAssetId).
        board_setup_config: Optional BoardSetupConfig (peg/holder pickup positions).
        wire_routing_config: Optional WireRoutingConfig (wire-end pickup positions).
        manufacturer_name: Organisation operating the station.

    Returns:
        MaterialDeliveryAASBundle with shell and two submodels.
    """
    safe_id = station_id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:delivery:{safe_id}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    delivery_id = f"{global_asset_id}/submodel/MaterialDelivery"

    n_objects = len(board_setup_config.pickup_positions) if board_setup_config else 0
    n_wire_ends = len(wire_routing_config.wire_end_pickups) if wire_routing_config else 0

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=station_id,
        manufacturer_product_designation=(
            f"Material delivery configuration for station {station_id}: "
            f"{n_objects} object pickups, {n_wire_ends} wire-end pickups"
        ),
        manufacturer_product_family="MaterialDeliveryStation",
        manufacturer_product_type="WireHarnessAssemblyMaterial",
    )

    delivery_sm = build_material_delivery(
        delivery_id,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
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
        submodel={_sm_ref(nameplate), _sm_ref(delivery_sm)},
    )

    return MaterialDeliveryAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        delivery_submodel=delivery_sm,
    )
