"""
Bridge from CDM + Layout + BoP pipeline to simulation motion plans.

Loads a CDM harness, generates the board layout, derives a Bill of Process,
and converts each BOARD_SETUP step into a concrete motion plan with 3D
world-frame poses and robot assignments.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from simulation.core.ConfigModels import (
    BoardSetupConfig,
    GraspOrientationConfig,
    ObjectPickupConfig,
    RobotDefinition,
)
from simulation.core.CoordinateTransform import AxisMapping, BoardToWorldTransform, WorldToRobotBaseTransform
from simulation.planning.GraspOrientationPlanner import GraspOrientationPlanner
from simulation.planning.PlanningModels import PoseTarget

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPModels import (
    PhaseType,
    PlaceConnectorHolderParameters,
    PlacePegParameters,
    ProcessType,
)
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import (
    BoardConfig as LayoutBoardConfig,
    ConnectorOccurrence as LayoutConnectorOccurrence,
    LayoutParameters,
    LayoutRequest,
    LayoutResponse,
    WireHarness,
)

logger = logging.getLogger(__name__)


class BoardSetupMotionPlan(BaseModel):
    """Concrete motion plan for picking and placing a single object.

    All *_pose fields are in the robot base frame (for the IK solver).
    The *_world_m fields store the original world-frame position
    for overlay rendering and diagnostics.
    """
    step_id: str
    object_id: str
    object_type: Literal["peg", "connector_holder"]
    robot_name: str
    pickup_pose: PoseTarget
    pickup_approach_pose: PoseTarget
    pickup_retreat_pose: PoseTarget
    pickup_transport_pose: PoseTarget
    placement_transport_pose: PoseTarget
    placement_pose: PoseTarget
    placement_approach_pose: PoseTarget
    placement_retreat_pose: PoseTarget
    pickup_world_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    placement_world_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    placement_orientation_deg: float = 0.0
    pickup_orientation_deg: float = 0.0


class PreflightError(Exception):
    """Raised when preflight validation detects a config mismatch."""


_raw_connector_data_cache: Dict[str, List[dict]] = {}


def loadHarnessFromJson(cdm_file_path: str) -> WireHarness:
    file_path = Path(cdm_file_path)
    with file_path.open("r", encoding="utf-8") as file_handle:
        raw_data = json.load(file_handle)

    _raw_connector_data_cache[cdm_file_path] = raw_data.get("connector_occurrences", [])
    return WireHarness.model_validate(raw_data)


def _upgradeConnectorOccurrences(
    harness: WireHarness,
    raw_connector_data: Optional[List[dict]] = None,
) -> WireHarness:
    """Convert CDM ConnectorOccurrences to the layout-extended type.

    The layout generator expects ConnectorOccurrence with an optional
    ``node_id`` field.  The base CDM pydantic model silently strips
    ``node_id`` during validation, so we recover it from three sources
    (in priority order):

    1. ``node_id`` already present in the raw JSON data.
    2. Position-based proximity matching to topology nodes.
    3. ``None`` (the connector will be skipped by the placement engine).
    """
    raw_lookup: Dict[str, dict] = {}
    if raw_connector_data:
        for raw_entry in raw_connector_data:
            raw_id = raw_entry.get("id")
            if raw_id:
                raw_lookup[raw_id] = raw_entry

    node_lookup = {node.id: node for node in harness.nodes}

    connector_node_map: Dict[str, Optional[str]] = {}

    for connector_occ in harness.connector_occurrences:
        raw_entry = raw_lookup.get(connector_occ.id, {})
        raw_node_id = raw_entry.get("node_id")
        if raw_node_id and raw_node_id in node_lookup:
            connector_node_map[connector_occ.id] = raw_node_id
            continue

        if connector_occ.position is not None:
            for node in harness.nodes:
                if (
                    abs(connector_occ.position.coord_x - node.position.coord_x) < 1.0
                    and abs(connector_occ.position.coord_y - node.position.coord_y) < 1.0
                ):
                    connector_node_map[connector_occ.id] = node.id
                    break

    extended_occurrences = []
    for connector_occ in harness.connector_occurrences:
        data = connector_occ.model_dump()
        data["node_id"] = connector_node_map.get(connector_occ.id)
        extended_occurrences.append(LayoutConnectorOccurrence.model_validate(data))

    harness.connector_occurrences = extended_occurrences
    return harness


@dataclass
class LayoutResult:
    """Layout response together with the board config used to generate it."""
    response: LayoutResponse
    board_width_mm: float
    board_height_mm: float


def generateLayout(
    harness: WireHarness,
    cdm_file_path: Optional[str] = None,
    intersection_offset_mm: float = 0.0,
) -> LayoutResult:
    raw_data = _raw_connector_data_cache.get(cdm_file_path) if cdm_file_path else None
    upgraded_harness = _upgradeConnectorOccurrences(harness, raw_data)

    if upgraded_harness.nodes:
        all_x = [node.position.coord_x for node in upgraded_harness.nodes]
        all_y = [node.position.coord_y for node in upgraded_harness.nodes]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        padding = 150.0
        board_width = max(max_x + padding, max_x - min_x + 2 * padding, 600.0)
        board_height = max(max_y + padding, max_y - min_y + 2 * padding, 400.0)
        offset_x = -min_x + padding
        offset_y = -min_y + padding
    else:
        board_width, board_height = 1200.0, 800.0
        offset_x, offset_y = 0.0, 0.0

    board_config = LayoutBoardConfig(
        width_mm=board_width,
        height_mm=board_height,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    parameters = LayoutParameters(intersection_offset_mm=intersection_offset_mm)
    request = LayoutRequest(
        harness=upgraded_harness,
        board_config=board_config,
        parameters=parameters,
    )
    service = LayoutGeneratorService()
    layout_response = service.generate_layout(request)
    return LayoutResult(
        response=layout_response,
        board_width_mm=board_width,
        board_height_mm=board_height,
    )


def _assignRobot(
    placement_position_m: Tuple[float, float, float],
    robot_definitions: List[RobotDefinition],
) -> str:
    best_robot_name = robot_definitions[0].robot_name
    best_distance = float("inf")

    for robot_def in robot_definitions:
        base_pos = robot_def.base_position_m
        distance = math.sqrt(
            (placement_position_m[0] - base_pos[0]) ** 2
            + (placement_position_m[1] - base_pos[1]) ** 2
            + (placement_position_m[2] - base_pos[2]) ** 2
        )
        if distance < best_distance:
            best_distance = distance
            best_robot_name = robot_def.robot_name

    return best_robot_name


def _buildPickupLookup(
    pickup_positions: List[ObjectPickupConfig],
) -> Dict[str, ObjectPickupConfig]:
    return {pickup.object_id: pickup for pickup in pickup_positions}


def _buildGraspLookup(
    grasp_orientations: List[GraspOrientationConfig],
) -> Dict[str, GraspOrientationConfig]:
    return {grasp.object_type: grasp for grasp in grasp_orientations}


def _preflightValidation(
    required_object_ids: List[str],
    pickup_lookup: Dict[str, ObjectPickupConfig],
) -> None:
    missing_ids = [oid for oid in required_object_ids if oid not in pickup_lookup]
    if missing_ids:
        raise PreflightError(
            f"Missing pickup positions for objects: {missing_ids}. "
            f"Available pickup IDs: {sorted(pickup_lookup.keys())}"
        )


def generateMotionPlans(
    harness: WireHarness,
    layout_result: LayoutResult,
    board_setup_config: BoardSetupConfig,
    board_transform: BoardToWorldTransform,
    robot_definitions: List[RobotDefinition],
    station_id: str = "assembly_station_1",
) -> List[BoardSetupMotionPlan]:
    """Generate motion plans for all BOARD_SETUP steps.

    Runs the BoP generator, extracts BOARD_SETUP phase, and converts
    each step into a concrete motion plan with robot-base-frame poses
    (required by the Pinocchio IK solver).
    """
    layout_response = layout_result.response
    bop_config = BoPGeneratorConfig(
        production_id="sim_board_setup",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_response,
                station_id=station_id,
            )
        ],
    )
    bop_service = BoPGeneratorService()
    production_bop = bop_service.generate(bop_config)

    board_setup_phase = None
    for phase in production_bop.phases:
        if phase.phase_type == PhaseType.BOARD_SETUP:
            board_setup_phase = phase
            break

    if board_setup_phase is None or not board_setup_phase.steps:
        logger.warning("No BOARD_SETUP phase found in generated BoP.")
        return []

    pickup_lookup = _buildPickupLookup(board_setup_config.pickup_positions)
    grasp_lookup = _buildGraspLookup(board_setup_config.grasp_orientations)
    orientation_planner = GraspOrientationPlanner(
        seed=board_setup_config.random_orientation_seed,
    )

    robot_base_transforms: Dict[str, WorldToRobotBaseTransform] = {
        robot_def.robot_name: WorldToRobotBaseTransform.fromRobotDefinition(robot_def)
        for robot_def in robot_definitions
    }

    required_ids: List[str] = []
    for step in board_setup_phase.steps:
        if step.process_type == ProcessType.PLACE_PEG:
            params: PlacePegParameters = step.parameters
            required_ids.append(params.peg_id)
        elif step.process_type == ProcessType.PLACE_CONNECTOR_HOLDER:
            params: PlaceConnectorHolderParameters = step.parameters
            required_ids.append(params.connector_occurrence_id)

    _preflightValidation(required_ids, pickup_lookup)

    approach_offset = board_setup_config.approach_offset_m
    retreat_offset = board_setup_config.retreat_offset_m
    transport_offset = board_setup_config.transport_height_offset_m

    motion_plans: List[BoardSetupMotionPlan] = []

    for step in board_setup_phase.steps:
        if step.process_type == ProcessType.PLACE_PEG:
            peg_params: PlacePegParameters = step.parameters
            object_id = peg_params.peg_id
            object_type = "peg"
            layout_x_mm = peg_params.position_x_mm
            layout_y_mm = peg_params.position_y_mm
            orientation_deg = peg_params.orientation_deg

        elif step.process_type == ProcessType.PLACE_CONNECTOR_HOLDER:
            holder_params: PlaceConnectorHolderParameters = step.parameters
            object_id = holder_params.connector_occurrence_id
            object_type = "connector_holder"
            layout_x_mm = holder_params.position_x_mm
            layout_y_mm = holder_params.position_y_mm
            orientation_deg = holder_params.orientation_deg
        else:
            continue

        pickup_config = pickup_lookup[object_id]
        grasp_config = grasp_lookup.get(object_type)

        if grasp_config is not None:
            base_grasp_quat = grasp_config.grasp_quat_wxyz
        else:
            base_grasp_quat = (0.0, 0.7071, -0.7071, 0.0)

        world_orientation_deg = board_transform.axis_mapping.transformOrientationDeg(
            orientation_deg,
        )

        random_pickup_deg = orientation_planner.generatePickupOrientation(object_id)
        grasp_plan = orientation_planner.computeGraspPlan(
            base_grasp_quat_wxyz=base_grasp_quat,
            pickup_orientation_deg=random_pickup_deg,
            placement_orientation_deg=world_orientation_deg,
        )

        pickup_quat = grasp_plan.pickup_grasp_quat_wxyz
        placement_quat = grasp_plan.placement_grasp_quat_wxyz

        if not grasp_plan.is_feasible:
            logger.warning(
                "  %s '%s': wrist delta %.1f deg infeasible, using placement quat for both",
                object_type, object_id, grasp_plan.wrist_delta_deg,
            )
            pickup_quat = placement_quat

        placement_world = board_transform.transformToWorld(layout_x_mm, layout_y_mm)
        robot_name = _assignRobot(placement_world, robot_definitions)
        robot_base_tf = robot_base_transforms[robot_name]

        board_surface_z = board_transform.getBoardSurfaceZ()

        placement_approach_world = (
            placement_world[0],
            placement_world[1],
            placement_world[2] + approach_offset,
        )
        placement_retreat_world = (
            placement_world[0],
            placement_world[1],
            placement_world[2] + retreat_offset,
        )
        placement_transport_world = (
            placement_world[0],
            placement_world[1],
            board_surface_z + transport_offset,
        )

        pickup_world = pickup_config.pickup_position_m
        pickup_approach_world = (
            pickup_world[0],
            pickup_world[1],
            pickup_world[2] + approach_offset,
        )
        pickup_retreat_world = (
            pickup_world[0],
            pickup_world[1],
            pickup_world[2] + retreat_offset,
        )
        pickup_transport_world = (
            pickup_world[0],
            pickup_world[1],
            board_surface_z + transport_offset,
        )

        placement_pose = robot_base_tf.transformPose(placement_world, placement_quat)
        placement_approach = robot_base_tf.transformPose(placement_approach_world, placement_quat)
        placement_retreat = robot_base_tf.transformPose(placement_retreat_world, placement_quat)
        placement_transport = robot_base_tf.transformPose(placement_transport_world, placement_quat)

        pickup_pose = robot_base_tf.transformPose(pickup_world, pickup_quat)
        pickup_approach = robot_base_tf.transformPose(pickup_approach_world, pickup_quat)
        pickup_retreat = robot_base_tf.transformPose(pickup_retreat_world, pickup_quat)
        pickup_transport = robot_base_tf.transformPose(pickup_transport_world, pickup_quat)

        logger.debug(
            "  %s '%s': pickup_yaw=%.1f° placement_yaw=%.1f° delta=%.1f°",
            object_type, object_id,
            random_pickup_deg, world_orientation_deg, grasp_plan.wrist_delta_deg,
        )

        motion_plans.append(
            BoardSetupMotionPlan(
                step_id=step.step_id,
                object_id=object_id,
                object_type=object_type,
                robot_name=robot_name,
                pickup_pose=pickup_pose,
                pickup_approach_pose=pickup_approach,
                pickup_retreat_pose=pickup_retreat,
                pickup_transport_pose=pickup_transport,
                placement_transport_pose=placement_transport,
                placement_pose=placement_pose,
                placement_approach_pose=placement_approach,
                placement_retreat_pose=placement_retreat,
                pickup_world_m=pickup_world,
                placement_world_m=placement_world,
                placement_orientation_deg=world_orientation_deg,
                pickup_orientation_deg=random_pickup_deg,
            )
        )

    logger.info(
        "Generated %d board setup motion plans (%d pegs, %d holders)",
        len(motion_plans),
        sum(1 for m in motion_plans if m.object_type == "peg"),
        sum(1 for m in motion_plans if m.object_type == "connector_holder"),
    )
    return motion_plans
