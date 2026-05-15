"""
Custom submodel: WorkcellConfiguration (urn:NEXUS:submodel:WorkcellConfiguration:1-0).

Encodes the full physical configuration of the robotic assembly workcell:
  - AssemblyBoard: dimensions and pose
  - Robots: each UR10e arm (base pose, joint limits, home configuration)
  - Grippers: Robotiq 2F-85 specs per robot
  - PegCatalog: available peg shape types
  - WorkspaceZones: 6 named mutual-exclusion zones

Built from simulation/core/ConfigModels.py instances.
"""

from typing import List, Optional, Tuple

import basyx.aas.model as model

from ..semantic_ids import WorkcellConfiguration as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: float) -> model.Property:
    return model.Property(id_short, value_type=float, value=value)


def _bool_prop(id_short: str, value: bool) -> model.Property:
    return model.Property(id_short, value_type=bool, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


def _vec3_smc(id_short: str, xyz: Tuple[float, float, float]) -> model.SubmodelElementCollection:
    return model.SubmodelElementCollection(
        id_short,
        value=[
            model.Property("X", value_type=float, value=xyz[0]),
            model.Property("Y", value_type=float, value=xyz[1]),
            model.Property("Z", value_type=float, value=xyz[2]),
        ],
    )


def _quat_smc(id_short: str, wxyz: Tuple[float, float, float, float]) -> model.SubmodelElementCollection:
    return model.SubmodelElementCollection(
        id_short,
        value=[
            model.Property("W", value_type=float, value=wxyz[0]),
            model.Property("X", value_type=float, value=wxyz[1]),
            model.Property("Y", value_type=float, value=wxyz[2]),
            model.Property("Z", value_type=float, value=wxyz[3]),
        ],
    )


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------

def _build_board_smc(board_config) -> model.SubmodelElementCollection:
    elems = [
        _float_prop("LengthM", board_config.length_m),
        _float_prop("WidthM", board_config.width_m),
        _float_prop("ThicknessM", board_config.thickness_m),
        _vec3_smc("PositionM", board_config.position_m),
    ]
    return model.SubmodelElementCollection(
        "AssemblyBoard", value=elems, semantic_id=_sem(SM_IDs.BOARD)
    )


def _build_robot_smc(robot_def, index: int) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        _str_prop("RobotName", robot_def.robot_name),
        _vec3_smc("BasePositionM", robot_def.base_position_m),
        _quat_smc("BaseQuatWXYZ", robot_def.base_quat_wxyz),
    ]

    # Joint names
    joint_name_props = [
        model.Property(None, value_type=str, value=name)
        for name in robot_def.joint_names
    ]
    elems.append(
        model.SubmodelElementList(
            "JointNames",
            type_value_list_element=model.Property,
            value_type_list_element=str,
            value=joint_name_props,
        )
    )

    # Home joint angles (rad)
    home_angle_props = [
        model.Property(None, value_type=float, value=angle)
        for angle in robot_def.home_joint_angles_rad
    ]
    elems.append(
        model.SubmodelElementList(
            "HomeJointAnglesRad",
            type_value_list_element=model.Property,
            value_type_list_element=float,
            value=home_angle_props,
        )
    )

    # Joint limits as list of [lower, upper] pairs
    limit_smcs = []
    for lower, upper in robot_def.joint_limits_rad:
        limit_smcs.append(
            model.SubmodelElementCollection(
                None,
                value=[
                    model.Property("Lower", value_type=float, value=lower),
                    model.Property("Upper", value_type=float, value=upper),
                ],
            )
        )
    elems.append(
        model.SubmodelElementList(
            "JointLimitsRad",
            type_value_list_element=model.SubmodelElementCollection,
            value=limit_smcs,
        )
    )

    return model.SubmodelElementCollection(
        f"Robot{index}",
        value=elems,
        semantic_id=_sem(SM_IDs.ROBOT),
    )


def _build_gripper_smc(gripper_def, index: int) -> model.SubmodelElementCollection:
    elems = [
        _str_prop("RobotName", gripper_def.robot_name),
        _float_prop("OpenCommandValue", gripper_def.open_command_value),
        _float_prop("CloseCommandValue", gripper_def.close_command_value),
        _float_prop("DefaultGripForceN", gripper_def.default_grip_force_n),
        _float_prop("FingerMaxWidthM", gripper_def.finger_max_width_m),
    ]
    return model.SubmodelElementCollection(
        f"Gripper{index}",
        value=elems,
        semantic_id=_sem(SM_IDs.GRIPPER),
    )


def _build_peg_shape_smc(peg_type: str, peg_shape) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        _str_prop("PegShapeType", peg_shape.peg_shape_type),
        _float_prop("PostRadiusM", peg_shape.post_radius_m),
        _float_prop("PostHeightM", peg_shape.post_height_m),
    ]
    if peg_shape.prong_length_m > 0:
        elems.append(_float_prop("ProngLengthM", peg_shape.prong_length_m))
    if peg_shape.prong_width_m > 0:
        elems.append(_float_prop("ProngWidthM", peg_shape.prong_width_m))
    if peg_shape.prong_gap_m > 0:
        elems.append(_float_prop("ProngGapM", peg_shape.prong_gap_m))
    if peg_shape.crossbar_length_m > 0:
        elems.append(_float_prop("CrossbarLengthM", peg_shape.crossbar_length_m))
    if peg_shape.crossbar_width_m > 0:
        elems.append(_float_prop("CrossbarWidthM", peg_shape.crossbar_width_m))
    # Sanitise key for idShort
    safe_key = peg_type.replace("-", "_").replace(" ", "_")
    return model.SubmodelElementCollection(
        f"PegShape_{safe_key}",
        value=elems,
        semantic_id=_sem(SM_IDs.PEG_SHAPE),
    )


def _build_board_setup_params_smc(board_setup_config) -> model.SubmodelElementCollection:
    """Encode BoardSetupConfig parameters as an SMC for reference."""
    elems = [
        _float_prop("ApproachOffsetM", board_setup_config.approach_offset_m),
        _float_prop("RetreatOffsetM", board_setup_config.retreat_offset_m),
        _float_prop("TransportHeightOffsetM", board_setup_config.transport_height_offset_m),
        _float_prop("PickupClearanceRadiusM", board_setup_config.pickup_clearance_radius_m),
    ]
    return model.SubmodelElementCollection("BoardSetupParams", value=elems)


def _build_wire_routing_params_smc(wire_routing_config) -> model.SubmodelElementCollection:
    """Encode WireRoutingConfig parameters as an SMC."""
    elems = [
        _float_prop("PegPassHeightOffsetM", wire_routing_config.peg_pass_height_offset_m),
        _float_prop("BetweenPegHeightOffsetM", wire_routing_config.between_peg_height_offset_m),
        _float_prop("InsertionPreAdjustmentM", wire_routing_config.insertion_pre_adjustment_m),
        _float_prop("RegraspRetractM", wire_routing_config.regrasp_retract_m),
        _float_prop("InsertionApproachDistanceM", wire_routing_config.insertion_approach_distance_m),
        _float_prop("CableHangHeightM", wire_routing_config.cable_hang_height_m),
    ]
    # Pull-test thresholds
    pt_smcs = []
    for pt in (wire_routing_config.pull_test_thresholds or []):
        pt_smcs.append(
            model.SubmodelElementCollection(
                None,
                value=[
                    _float_prop("MinCrossSectionMm2", pt.min_cross_section_mm2),
                    _float_prop("MaxCrossSectionMm2", pt.max_cross_section_mm2),
                    _float_prop("ThresholdForceN", pt.threshold_force_n),
                ],
            )
        )
    if pt_smcs:
        elems.append(
            model.SubmodelElementList(
                "PullTestThresholds",
                type_value_list_element=model.SubmodelElementCollection,
                value=pt_smcs,
            )
        )
    return model.SubmodelElementCollection("WireRoutingParams", value=elems)


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_workcell_configuration(
    submodel_id: str,
    station_config,
    robots_config,
    grippers_config,
    scene_objects_config=None,
    board_setup_config=None,
    wire_routing_config=None,
) -> model.Submodel:
    """Build a WorkcellConfiguration submodel from simulation config objects.

    Args:
        submodel_id: The unique AAS submodel ID.
        station_config: StationConfig (board dimensions, world frame, viewer).
        robots_config: RobotsConfig (robot definitions + asset sources).
        grippers_config: GrippersConfig (gripper definitions).
        scene_objects_config: Optional SceneObjectsConfig (peg catalog).
        board_setup_config: Optional BoardSetupConfig (approach/retreat params).
        wire_routing_config: Optional WireRoutingConfig (routing params).

    Returns:
        A Submodel encoding the full workcell configuration.
    """
    elements: list[model.SubmodelElement] = []

    # Board
    elements.append(_build_board_smc(station_config.board))

    # Robots
    for i, robot_def in enumerate(robots_config.robots):
        elements.append(_build_robot_smc(robot_def, i))

    # Grippers
    gripper_type_prop = _str_prop("GripperType", grippers_config.gripper_type)
    elements.append(gripper_type_prop)
    for i, gripper_def in enumerate(grippers_config.grippers):
        elements.append(_build_gripper_smc(gripper_def, i))

    # Peg catalog
    if scene_objects_config is not None and scene_objects_config.peg_catalog:
        peg_shape_smcs = [
            _build_peg_shape_smc(peg_type, peg_shape)
            for peg_type, peg_shape in scene_objects_config.peg_catalog.items()
        ]
        elements.append(
            model.SubmodelElementCollection(
                "PegCatalog",
                value=peg_shape_smcs,
            )
        )

    # BoardSetup parameters
    if board_setup_config is not None:
        elements.append(_build_board_setup_params_smc(board_setup_config))

    # WireRouting parameters
    if wire_routing_config is not None:
        elements.append(_build_wire_routing_params_smc(wire_routing_config))

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
