"""
WorkspaceZonesAAS — Resource AAS for the shared robot workspace layout.

Carries two submodels:
  1. DigitalNameplate    (IDTA 02006-2-0)
  2. WorkspaceZones      (urn:NEXUS:submodel:WorkspaceZones:1-0)

GlobalAssetId convention:
    urn:NEXUS:workspace:{station_id}
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.workspace_zones import build_workspace_zones


@dataclass
class WorkspaceZonesAASBundle:
    """A complete WorkspaceZonesAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    zones_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.zones_submodel]


def build_workspace_zones_aas(
    station_id: str,
    robots_config,
    station_config,
    board_setup_config=None,
    safety_policy: str = "STRICT_WAIT",
    max_wait_time_s: float = 120.0,
    max_retry_count: int = 200,
    manufacturer_name: str = "NEXUS",
) -> WorkspaceZonesAASBundle:
    """Build a complete WorkspaceZonesAAS from simulation config objects.

    Args:
        station_id: Station identifier (used in GlobalAssetId).
        robots_config: RobotsConfig (robot definitions with base positions).
        station_config: StationConfig (board dimensions for center-X derivation).
        board_setup_config: Optional BoardSetupConfig for pickup clearance radius.
        safety_policy: SafetyPolicy string ("STRICT_WAIT" | "OPTIMISTIC").
        max_wait_time_s: Maximum robot wait time.
        max_retry_count: Maximum scheduling retries.
        manufacturer_name: Organisation operating the station.

    Returns:
        WorkspaceZonesAASBundle with shell and two submodels.
    """
    safe_id = station_id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:workspace:{safe_id}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    zones_id = f"{global_asset_id}/submodel/WorkspaceZones"

    robot_names = [r.robot_name for r in robots_config.robots]
    robot_base_positions: Dict[str, Tuple[float, float, float]] = {
        r.robot_name: r.base_position_m for r in robots_config.robots
    }

    # Board center X from station config board position + half-length
    board_center_x = (
        station_config.board.position_m[0]
        + station_config.board.length_m / 2.0
    )

    pickup_clearance_radius_m = (
        board_setup_config.pickup_clearance_radius_m
        if board_setup_config is not None
        else 0.45
    )

    # Home joint angles from first robot definition (shared default)
    home_angles: Optional[List[float]] = None
    if robots_config.robots:
        home_angles = list(robots_config.robots[0].home_joint_angles_rad)

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=station_id,
        manufacturer_product_designation=(
            f"Workspace zone configuration for station {station_id}: "
            f"{len(robot_names)} robots, {safety_policy} safety policy"
        ),
        manufacturer_product_family="WorkspaceZoneConfiguration",
        manufacturer_product_type="MultiRobotCoordination",
    )

    zones_sm = build_workspace_zones(
        zones_id,
        robot_names=robot_names,
        robot_base_positions=robot_base_positions,
        board_center_x=board_center_x,
        pickup_clearance_radius_m=pickup_clearance_radius_m,
        safety_policy=safety_policy,
        max_wait_time_s=max_wait_time_s,
        max_retry_count=max_retry_count,
        home_joint_angles=home_angles,
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
        submodel={_sm_ref(nameplate), _sm_ref(zones_sm)},
    )

    return WorkspaceZonesAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        zones_submodel=zones_sm,
    )
