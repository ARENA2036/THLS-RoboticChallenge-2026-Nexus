"""
Config → AAS builder.

Converts simulation config objects into an AssemblyStationAAS.

Usage:
    from aas.builders.config_to_aas import build_aas_from_config
    bundle = build_aas_from_config(
        station_id="station_01",
        station_config=station_cfg,
        robots_config=robots_cfg,
        grippers_config=grippers_cfg,
    )
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from ..shells.assembly_station_aas import (
    build_assembly_station_aas,
    AssemblyStationAASBundle,
)


def build_aas_from_config(
    station_id: str,
    station_config,
    robots_config,
    grippers_config,
    scene_objects_config=None,
    board_setup_config=None,
    wire_routing_config=None,
    manufacturer_name: str = "NEXUS",
) -> AssemblyStationAASBundle:
    """Build an AssemblyStationAAS from simulation config objects.

    Args:
        station_id: Unique station identifier.
        station_config: StationConfig from simulation/core/ConfigModels.py.
        robots_config: RobotsConfig from simulation/core/ConfigModels.py.
        grippers_config: GrippersConfig from simulation/core/ConfigModels.py.
        scene_objects_config: Optional SceneObjectsConfig.
        board_setup_config: Optional BoardSetupConfig.
        wire_routing_config: Optional WireRoutingConfig.
        manufacturer_name: Organisation name for the nameplate.

    Returns:
        AssemblyStationAASBundle with shell and three submodels.
    """
    return build_assembly_station_aas(
        station_id=station_id,
        station_config=station_config,
        robots_config=robots_config,
        grippers_config=grippers_config,
        scene_objects_config=scene_objects_config,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
        manufacturer_name=manufacturer_name,
    )
