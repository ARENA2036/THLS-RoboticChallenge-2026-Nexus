"""
Builder: SimConfig objects → WorkspaceZonesAAS.
"""

from ..shells.workspace_zones_aas import (
    WorkspaceZonesAASBundle,
    build_workspace_zones_aas,
)


def build_aas_from_workspace(
    station_id: str,
    robots_config,
    station_config,
    board_setup_config=None,
    safety_policy: str = "STRICT_WAIT",
    max_wait_time_s: float = 120.0,
    max_retry_count: int = 200,
    manufacturer_name: str = "NEXUS",
) -> WorkspaceZonesAASBundle:
    """Build a WorkspaceZonesAAS from simulation config objects.

    Args:
        station_id: Station identifier.
        robots_config: RobotsConfig (robot definitions with base positions).
        station_config: StationConfig (board dimensions).
        board_setup_config: Optional BoardSetupConfig for pickup clearance radius.
        safety_policy: SafetyPolicy string ("STRICT_WAIT" | "OPTIMISTIC").
        max_wait_time_s: Maximum robot wait time.
        max_retry_count: Maximum scheduling retries.
        manufacturer_name: Organisation operating the station.

    Returns:
        WorkspaceZonesAASBundle (shell + 2 submodels).
    """
    return build_workspace_zones_aas(
        station_id,
        robots_config,
        station_config,
        board_setup_config=board_setup_config,
        safety_policy=safety_policy,
        max_wait_time_s=max_wait_time_s,
        max_retry_count=max_retry_count,
        manufacturer_name=manufacturer_name,
    )
