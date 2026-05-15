"""
AssemblyStationAAS — Resource AAS for the robotic assembly workcell.

Carries three submodels:
  1. DigitalNameplate       (IDTA 02006-2-0)
  2. CapabilityDescription  (IDTA 02020-1-0)
  3. WorkcellConfiguration  (urn:NEXUS:submodel:WorkcellConfiguration:1-0)

GlobalAssetId convention:
    urn:NEXUS:station:{station_id}
"""

from dataclasses import dataclass

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.capability_description import build_capability_description
from ..submodels.workcell_configuration import build_workcell_configuration


@dataclass
class AssemblyStationAASBundle:
    """A complete AssemblyStationAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    capability_submodel: model.Submodel
    workcell_submodel: model.Submodel

    def all_objects(self) -> list:
        return [
            self.shell,
            self.nameplate_submodel,
            self.capability_submodel,
            self.workcell_submodel,
        ]


def build_assembly_station_aas(
    station_id: str,
    station_config,
    robots_config,
    grippers_config,
    scene_objects_config=None,
    board_setup_config=None,
    wire_routing_config=None,
    manufacturer_name: str = "NEXUS",
) -> AssemblyStationAASBundle:
    """Build a complete AssemblyStationAAS from simulation config objects.

    Args:
        station_id: Unique station identifier (used in GlobalAssetId and nameplate).
        station_config: StationConfig (board dimensions, world frame).
        robots_config: RobotsConfig (robot definitions).
        grippers_config: GrippersConfig (gripper definitions).
        scene_objects_config: Optional SceneObjectsConfig (peg catalog).
        board_setup_config: Optional BoardSetupConfig.
        wire_routing_config: Optional WireRoutingConfig.
        manufacturer_name: Organisation operating the station.

    Returns:
        AssemblyStationAASBundle with shell and three submodels.
    """
    global_asset_id = f"urn:NEXUS:station:{station_id}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    capability_id = f"{global_asset_id}/submodel/CapabilityDescription"
    workcell_id = f"{global_asset_id}/submodel/WorkcellConfiguration"

    # --- DigitalNameplate ---
    num_robots = len(robots_config.robots) if robots_config else 0
    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=station_id,
        manufacturer_product_designation=(
            f"Dual-arm robotic wire harness assembly station "
            f"({num_robots}x UR10e, {grippers_config.gripper_type})"
        ),
        manufacturer_product_family="RoboticAssemblyStation",
        manufacturer_product_type="WireHarnessAssemblyCell",
    )

    # --- CapabilityDescription ---
    capability = build_capability_description(
        capability_id,
        station_config,
        wire_routing_config=wire_routing_config,
    )

    # --- WorkcellConfiguration ---
    workcell = build_workcell_configuration(
        workcell_id,
        station_config,
        robots_config,
        grippers_config,
        scene_objects_config=scene_objects_config,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
    )

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
        submodel={_sm_ref(nameplate), _sm_ref(capability), _sm_ref(workcell)},
    )

    return AssemblyStationAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        capability_submodel=capability,
        workcell_submodel=workcell,
    )
