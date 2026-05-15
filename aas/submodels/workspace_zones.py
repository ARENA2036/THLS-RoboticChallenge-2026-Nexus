"""
Custom submodel: WorkspaceZones (urn:NEXUS:submodel:WorkspaceZones:1-0).

Describes the static spatial decomposition of the shared robot workspace:
  - BoardSplit: X-coordinate dividing left/right board halves
  - PickupZone: shared staging area with mutual-exclusion clearance radius
  - RobotBoardHalves: which board half each robot owns
  - SafetyPolicy: configured constraint-enforcement strategy
  - WaitLimits: maximum wait time and retry count

Corresponds to the coordination logic in simulation/planning/WorkspaceCoordinator.py.
This submodel captures the *static configuration* that WorkspaceCoordinator is
initialised with; runtime state is not persisted here.
"""

from typing import Dict, List, Optional, Tuple

import basyx.aas.model as model

from ..semantic_ids import WorkspaceZones as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: float) -> model.Property:
    return model.Property(id_short, value_type=float, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


def _bool_prop(id_short: str, value: bool) -> model.Property:
    return model.Property(id_short, value_type=bool, value=value)


def _vec3_smc(id_short: str | None, xyz: Tuple[float, float, float]) -> model.SubmodelElementCollection:
    return model.SubmodelElementCollection(
        id_short,
        value=[
            model.Property("X", value_type=float, value=xyz[0]),
            model.Property("Y", value_type=float, value=xyz[1]),
            model.Property("Z", value_type=float, value=xyz[2]),
        ],
    )


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------

def _build_board_split_smc(board_center_x: float) -> model.SubmodelElementCollection:
    """Named SMC describing the left/right board split."""
    return model.SubmodelElementCollection(
        "BoardSplit",
        value=[
            _float_prop("BoardCenterX", board_center_x),
            _str_prop("LeftHalf", "x <= BoardCenterX"),
            _str_prop("RightHalf", "x > BoardCenterX"),
        ],
    )


def _build_pickup_zone_smc(
    clearance_radius_m: float,
) -> model.SubmodelElementCollection:
    """Named SMC for the shared pickup/staging zone."""
    return model.SubmodelElementCollection(
        "PickupZone",
        value=[
            _str_prop("Policy", "MutualExclusion"),
            _float_prop("ClearanceRadiusM", clearance_radius_m),
            _str_prop("Description",
                      "Shared staging area near the component tray. "
                      "Only one robot may be inside ClearanceRadiusM at a time."),
        ],
        semantic_id=_sem(SM_IDs.PICKUP_ZONE),
    )


def _build_robot_assignment_smc(
    robot_name: str,
    base_position: Tuple[float, float, float],
    own_board_half: str,
    home_joint_angles: Optional[List[float]] = None,
) -> model.SubmodelElementCollection:
    """Named SMC for one robot's board-half assignment."""
    safe_name = robot_name.replace("-", "_").replace(" ", "_")
    elems = [
        _str_prop("RobotName", robot_name),
        _vec3_smc("BasePositionM", base_position),
        _str_prop("OwnBoardHalf", own_board_half),
        _str_prop("CrossHalfPolicy",
                  "MayEnterOtherHalfOnlyWhenOtherRobotAtHome"),
    ]
    if home_joint_angles:
        home_sml = model.SubmodelElementList(
            "HomeJointAnglesRad",
            type_value_list_element=model.Property,
            value_type_list_element=float,
            value=[
                model.Property(None, value_type=float, value=a)
                for a in home_joint_angles
            ],
        )
        elems.append(home_sml)
    return model.SubmodelElementCollection(
        f"Robot_{safe_name}",
        value=elems,
        semantic_id=_sem(SM_IDs.ROBOT_ASSIGNMENT),
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_workspace_zones(
    submodel_id: str,
    *,
    robot_names: List[str],
    robot_base_positions: Dict[str, Tuple[float, float, float]],
    board_center_x: float = 0.0,
    pickup_clearance_radius_m: float = 0.45,
    safety_policy: str = "STRICT_WAIT",
    max_wait_time_s: float = 120.0,
    max_retry_count: int = 200,
    home_joint_angles: Optional[List[float]] = None,
) -> model.Submodel:
    """Build a WorkspaceZones submodel from WorkspaceCoordinator init parameters.

    Args:
        submodel_id: Unique AAS submodel ID.
        robot_names: Ordered list of robot names (matching RobotsConfig).
        robot_base_positions: Map of robot_name → (x, y, z) base position in metres.
        board_center_x: X-coordinate (metres) that divides left/right board halves.
        pickup_clearance_radius_m: Mutual-exclusion radius around the pickup zone.
        safety_policy: SafetyPolicy enum value as string (e.g. "STRICT_WAIT").
        max_wait_time_s: Maximum time a robot will wait to acquire a zone.
        max_retry_count: Maximum retry attempts before raising a scheduling error.
        home_joint_angles: Optional shared home configuration (6-element list, rad).

    Returns:
        Populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    elements.append(_build_board_split_smc(board_center_x))
    elements.append(_build_pickup_zone_smc(pickup_clearance_radius_m))

    # Safety policy and wait limits
    elements.append(model.SubmodelElementCollection(
        "CoordinationPolicy",
        value=[
            _str_prop("SafetyPolicy", safety_policy, ),
            _float_prop("MaxWaitTimeS", max_wait_time_s),
            _int_prop("MaxRetryCount", max_retry_count),
        ],
        semantic_id=_sem(SM_IDs.SAFETY_POLICY),
    ))

    # Per-robot board-half assignments
    robot_assignments: list[model.SubmodelElement] = []
    for rname in robot_names:
        base_pos = robot_base_positions.get(rname, (0.0, 0.0, 0.0))
        own_half = "left" if base_pos[0] <= board_center_x else "right"
        robot_assignments.append(
            _build_robot_assignment_smc(rname, base_pos, own_half, home_joint_angles)
        )
    elements.append(model.SubmodelElementCollection(
        "RobotBoardHalves",
        value=robot_assignments,
        semantic_id=_sem(SM_IDs.BOARD_HALF),
    ))

    # Named zones summary
    zone_names = ["PickupZone", "LeftBoardHalf", "RightBoardHalf"]
    zone_summary = model.SubmodelElementList(
        "ZoneNames",
        type_value_list_element=model.Property,
        value_type_list_element=str,
        value=[model.Property(None, value_type=str, value=z) for z in zone_names],
    )
    elements.append(zone_summary)

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
