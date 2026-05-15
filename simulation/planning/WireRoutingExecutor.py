"""
Wire routing executor -- dual-arm independent-pace peg traversal with
mocked insertion and pull-test sub-actions.

Orchestrates the execution of a single ROUTE_WIRE BoP step:
  1. Compute middle-out peg split and extremity-to-robot assignment.
  2. Both robots pick up their wire end (independent pace, pickup zone
     exclusion via WorkspaceCoordinator).
  3. Each robot independently traverses its peg sequence at the
     configured heights.
  4. Each robot performs connector insertion with camera pre-adjustment,
     re-grasp, force completion check, and pull-test.
  5. Overlay events are emitted for cable-end, carried-cable, and
     routed-cable-segment visuals.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulation.core.ConfigModels import WireEndPickupConfig, WireRoutingConfig
from simulation.core.CoordinateTransform import WorldToRobotBaseTransform
from simulation.core.RotationUtils import composeZRotation
from simulation.interface.CameraMockService import CameraOrientationService
from simulation.interface.ForceTorqueMockService import (
    ForceProfile,
    ForceTorqueService,
)
from simulation.planning.MiddleOutPlanner import (
    assignExtremityToRobot,
    splitPegsMiddleOut,
)
from simulation.planning.MotionSequenceBuilder import MotionSequenceBuilder
from simulation.planning.PlanningModels import PoseTarget
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator

logger = logging.getLogger(__name__)

_DEFAULT_GRASP_QUAT_WXYZ = (0.0, 0.7071, -0.7071, 0.0)


@dataclass
class WireRoutingOverlayEvent:
    """Overlay event emitted during wire routing."""
    timestamp_s: float
    event_type: str
    object_id: str
    object_type: str
    position_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    robot_name: str = ""
    color_rgba: Tuple[float, float, float, float] = (0.95, 0.55, 0.1, 1.0)
    size_params: Dict = field(default_factory=dict)


@dataclass
class WireRoutingStepResult:
    """Result of routing a single wire."""
    success: bool
    wire_occurrence_id: str
    connection_id: str
    overlay_events: List[WireRoutingOverlayEvent] = field(default_factory=list)
    force_profiles: List[ForceProfile] = field(default_factory=list)
    error_message: Optional[str] = None
    routed_segments: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = field(
        default_factory=list,
    )


class WireRoutingExecutor:
    """Executes a ROUTE_WIRE step for two robots in independent-pace mode."""

    def __init__(
        self,
        motion_builders: Dict[str, MotionSequenceBuilder],
        coordinator: WorkspaceCoordinator,
        robot_base_transforms: Dict[str, WorldToRobotBaseTransform],
        camera_service: CameraOrientationService,
        force_torque_service: ForceTorqueService,
        wire_routing_config: WireRoutingConfig,
        home_joint_angles_by_robot: Dict[str, List[float]],
        robot_base_positions: Dict[str, Tuple[float, float, float]],
    ) -> None:
        self._motion_builders = motion_builders
        self._coordinator = coordinator
        self._robot_base_transforms = robot_base_transforms
        self._camera_service = camera_service
        self._ft_service = force_torque_service
        self._config = wire_routing_config
        self._home_joints = home_joint_angles_by_robot
        self._robot_bases = robot_base_positions
        self._routed_segments: List[
            Tuple[Tuple[float, float, float], Tuple[float, float, float]]
        ] = []

    def getRoutedSegments(
        self,
    ) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
        return list(self._routed_segments)

    def executeRouteWire(
        self,
        wire_occurrence_id: str,
        connection_id: str,
        ordered_peg_ids: List[str],
        peg_positions_world: Dict[str, Tuple[float, float, float]],
        extremity_connector_ids: List[str],
        connector_positions_world: Dict[str, Tuple[float, float, float]],
        wire_color_rgba: Tuple[float, float, float, float],
        wire_cross_section_mm2: float = 0.5,
        board_surface_z: float = 0.72,
        peg_crossbar_z: float = 0.0,
        peg_orientations_world: Optional[Dict[str, float]] = None,
        connector_orientations_world: Optional[Dict[str, float]] = None,
    ) -> WireRoutingStepResult:
        """Execute the full routing sequence for one wire."""
        if peg_orientations_world is None:
            peg_orientations_world = {}
        if connector_orientations_world is None:
            connector_orientations_world = {}

        overlay_events: List[WireRoutingOverlayEvent] = []
        force_profiles: List[ForceProfile] = []

        middle_out = splitPegsMiddleOut(
            ordered_peg_ids, peg_positions_world, self._robot_bases,
        )

        extremity_assignment = assignExtremityToRobot(
            connector_positions_world,
            extremity_connector_ids,
            self._robot_bases,
        )

        pull_threshold = self._resolvePullTestThreshold(wire_cross_section_mm2)

        if peg_crossbar_z <= 0.0:
            peg_crossbar_z = board_surface_z + 0.06

        pass_height = peg_crossbar_z + self._config.peg_pass_height_offset_m
        transit_height = pass_height + self._config.between_peg_height_offset_m

        robot_state: Dict[str, _RobotRoutingState] = {}

        for extremity_idx in range(min(2, len(extremity_connector_ids))):
            robot_name = extremity_assignment.getRobotForExtremity(extremity_idx)
            connector_id = extremity_connector_ids[extremity_idx]

            if robot_name == middle_out.left_robot_name:
                peg_sequence = middle_out.left_peg_sequence
            else:
                peg_sequence = middle_out.right_peg_sequence

            pickup_config = self._findWireEndPickupConfig(wire_occurrence_id, extremity_idx)
            if pickup_config is not None:
                pickup_position = pickup_config.pickup_position_m
                cable_axis_deg = pickup_config.cable_axis_orientation_deg
                anchor_position = pickup_config.anchor_position_m
            else:
                connector_pos = connector_positions_world.get(connector_id, (0.0, 0.0, board_surface_z))
                pickup_position = (connector_pos[0], connector_pos[1] - 0.15, board_surface_z + 0.03)
                cable_axis_deg = self._deriveCableAxisFromPegs(
                    pickup_position, peg_sequence, peg_positions_world,
                )
                anchor_position = None

            if anchor_position is None:
                anchor_position = (
                    pickup_position[0],
                    pickup_position[1],
                    pickup_position[2] + self._config.cable_hang_height_m,
                )

            robot_state[robot_name] = _RobotRoutingState(
                robot_name=robot_name,
                extremity_index=extremity_idx,
                connector_id=connector_id,
                peg_sequence=peg_sequence,
                pickup_position=pickup_position,
                cable_axis_orientation_deg=cable_axis_deg,
                anchor_position=anchor_position,
            )

        for robot_name, state in robot_state.items():
            cable_end_id = f"{wire_occurrence_id}_end_{state.extremity_index}"
            overlay_events.append(WireRoutingOverlayEvent(
                timestamp_s=0.0,
                event_type="ADD_CABLE_END",
                object_id=cable_end_id,
                object_type="cable_end",
                position_m=state.pickup_position,
                robot_name=robot_name,
                color_rgba=wire_color_rgba,
                size_params={
                    "anchor_position_m": state.anchor_position,
                },
            ))

        for robot_name, state in robot_state.items():
            pickup_result = self._executePickup(
                robot_name, state, wire_occurrence_id, wire_color_rgba,
                overlay_events, board_surface_z,
            )
            if not pickup_result:
                return WireRoutingStepResult(
                    success=False,
                    wire_occurrence_id=wire_occurrence_id,
                    connection_id=connection_id,
                    overlay_events=overlay_events,
                    error_message=f"Pickup failed for {robot_name}",
                )

        routed_segments: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = []

        for robot_name, state in robot_state.items():
            traverse_result = self._executePegTraversal(
                robot_name, state, peg_positions_world, peg_orientations_world,
                pass_height, transit_height, wire_occurrence_id,
                wire_color_rgba, overlay_events, routed_segments,
            )
            if not traverse_result:
                return WireRoutingStepResult(
                    success=False,
                    wire_occurrence_id=wire_occurrence_id,
                    connection_id=connection_id,
                    overlay_events=overlay_events,
                    routed_segments=routed_segments,
                    error_message=f"Peg traversal failed for {robot_name}",
                )

        for robot_name, state in robot_state.items():
            connector_pos = connector_positions_world.get(
                state.connector_id, (0.0, 0.0, board_surface_z),
            )
            connector_orientation = connector_orientations_world.get(
                state.connector_id, 0.0,
            )
            insertion_result, force_profile = self._executeInsertion(
                robot_name, state, connector_pos, connector_orientation,
                pull_threshold, wire_occurrence_id,
                wire_color_rgba, overlay_events, board_surface_z,
                routed_segments,
            )
            force_profiles.append(force_profile)
            if not insertion_result:
                return WireRoutingStepResult(
                    success=False,
                    wire_occurrence_id=wire_occurrence_id,
                    connection_id=connection_id,
                    overlay_events=overlay_events,
                    force_profiles=force_profiles,
                    routed_segments=routed_segments,
                    error_message=f"Insertion failed for {robot_name}",
                )

        for robot_name, state in robot_state.items():
            self._returnToHome(robot_name)

        self._routed_segments.extend(routed_segments)

        return WireRoutingStepResult(
            success=True,
            wire_occurrence_id=wire_occurrence_id,
            connection_id=connection_id,
            overlay_events=overlay_events,
            force_profiles=force_profiles,
            routed_segments=routed_segments,
        )

    # ------------------------------------------------------------------
    # Sub-actions
    # ------------------------------------------------------------------

    def _executePickup(
        self,
        robot_name: str,
        state: _RobotRoutingState,
        wire_occurrence_id: str,
        wire_color_rgba: Tuple[float, float, float, float],
        overlay_events: List[WireRoutingOverlayEvent],
        board_surface_z: float,
    ) -> bool:
        builder = self._motion_builders[robot_name]
        base_transform = self._robot_base_transforms[robot_name]
        home_joints = self._home_joints[robot_name]

        current_time = self._coordinator.getRobotState(robot_name).current_time_s
        pickup_time = self._coordinator.acquirePickupZone(robot_name)
        current_time = max(current_time, pickup_time)

        pickup_pos = state.pickup_position
        grasp_quat = _computePickupGraspQuat(state.cable_axis_orientation_deg)

        approach_pos = (pickup_pos[0], pickup_pos[1], pickup_pos[2] + 0.05)
        approach_pose = base_transform.transformPose(approach_pos, grasp_quat)
        pickup_pose = base_transform.transformPose(pickup_pos, grasp_quat)

        approach_joints = builder.computeJointAnglesForPose(robot_name, approach_pose, home_joints)
        if approach_joints is None:
            return False

        end_time = builder.queueMoveJ(
            robot_name, approach_joints, home_joints, current_time,
            description=f"WR pickup approach {wire_occurrence_id}",
        )
        if end_time is None:
            return False
        current_time = end_time

        if not builder.queueGripper(robot_name, self._config.gripper_open_value, current_time):
            return False
        current_time += self._config.gripper_settle_s

        end_time, pickup_joints = builder.queueMoveL(
            robot_name, pickup_pose, approach_joints, current_time,
            duration_s=1.0,
            description=f"WR pickup descend {wire_occurrence_id}",
        )
        if end_time is None:
            return False
        current_time = end_time

        if not builder.queueGripper(robot_name, self._config.gripper_close_value, current_time):
            return False
        current_time += self._config.gripper_settle_s

        retreat_pos = (pickup_pos[0], pickup_pos[1], pickup_pos[2] + 0.10)
        retreat_pose = base_transform.transformPose(retreat_pos, grasp_quat)
        end_time, retreat_joints = builder.queueMoveL(
            robot_name, retreat_pose, pickup_joints, current_time,
            duration_s=1.0,
            description=f"WR pickup retreat {wire_occurrence_id}",
        )
        if end_time is None:
            return False
        current_time = end_time

        self._coordinator.releasePickupZone(robot_name, current_time)
        self._coordinator.updateRobotTime(robot_name, current_time)

        state.current_joints = retreat_joints
        state.current_time = current_time

        cable_end_id = f"{wire_occurrence_id}_end_{state.extremity_index}"
        overlay_events.append(WireRoutingOverlayEvent(
            timestamp_s=current_time,
            event_type="REMOVE_CABLE_END",
            object_id=cable_end_id,
            object_type="cable_end",
            position_m=pickup_pos,
            robot_name=robot_name,
        ))
        carried_id = f"{wire_occurrence_id}_carried_{state.extremity_index}"
        overlay_events.append(WireRoutingOverlayEvent(
            timestamp_s=current_time,
            event_type="ADD_CARRIED_CABLE",
            object_id=carried_id,
            object_type="carried_cable",
            position_m=retreat_pos,
            robot_name=robot_name,
            color_rgba=wire_color_rgba,
        ))

        return True

    def _executePegTraversal(
        self,
        robot_name: str,
        state: _RobotRoutingState,
        peg_positions_world: Dict[str, Tuple[float, float, float]],
        peg_orientations_world: Dict[str, float],
        pass_height: float,
        transit_height: float,
        wire_occurrence_id: str,
        wire_color_rgba: Tuple[float, float, float, float],
        overlay_events: List[WireRoutingOverlayEvent],
        routed_segments: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]],
    ) -> bool:
        builder = self._motion_builders[robot_name]
        base_transform = self._robot_base_transforms[robot_name]
        slot_offset_m = self._config.peg_slot_offset_m

        current_joints = state.current_joints
        current_time = state.current_time
        previous_position: Optional[Tuple[float, float, float]] = None

        for peg_index, peg_id in enumerate(state.peg_sequence):
            peg_pos = peg_positions_world.get(peg_id, (0.0, 0.0, 0.0))
            peg_orientation_deg = peg_orientations_world.get(peg_id, 0.0)

            offset_x, offset_y = _computePegSlotOffset(
                peg_orientation_deg, slot_offset_m,
            )
            slot_pos = (peg_pos[0] + offset_x, peg_pos[1] + offset_y, 0.0)

            transit_pos = (slot_pos[0], slot_pos[1], transit_height)
            transit_pose = base_transform.transformPose(transit_pos, _DEFAULT_GRASP_QUAT_WXYZ)
            transit_joints = builder.computeJointAnglesForPose(
                robot_name, transit_pose, current_joints,
            )
            if transit_joints is None:
                return False

            end_time = builder.queueMoveJ(
                robot_name, transit_joints, current_joints, current_time,
                description=f"WR transit to peg {peg_id}",
            )
            if end_time is None:
                return False
            current_time = end_time

            pass_pos = (slot_pos[0], slot_pos[1], pass_height)
            pass_pose = base_transform.transformPose(pass_pos, _DEFAULT_GRASP_QUAT_WXYZ)
            end_time, pass_joints = builder.queueMoveL(
                robot_name, pass_pose, transit_joints, current_time,
                duration_s=0.8,
                description=f"WR pass through peg {peg_id}",
            )
            if end_time is None:
                return False
            current_time = end_time

            end_time, back_up_joints = builder.queueMoveL(
                robot_name, transit_pose, pass_joints, current_time,
                duration_s=0.8,
                description=f"WR lift after peg {peg_id}",
            )
            if end_time is None:
                return False
            current_time = end_time

            current_joints = back_up_joints

            if previous_position is not None:
                segment = (previous_position, pass_pos)
                routed_segments.append(segment)
                segment_id = f"{wire_occurrence_id}_seg_{peg_index}"
                overlay_events.append(WireRoutingOverlayEvent(
                    timestamp_s=current_time,
                    event_type="ADD_ROUTED_SEGMENT",
                    object_id=segment_id,
                    object_type="routed_cable_segment",
                    position_m=pass_pos,
                    robot_name=robot_name,
                    color_rgba=wire_color_rgba,
                    size_params={
                        "start_position_m": previous_position,
                        "end_position_m": pass_pos,
                    },
                ))

            previous_position = pass_pos

        self._coordinator.updateRobotTime(robot_name, current_time)
        state.current_joints = current_joints
        state.current_time = current_time
        state.last_peg_position = previous_position
        return True

    def _executeInsertion(
        self,
        robot_name: str,
        state: _RobotRoutingState,
        connector_position: Tuple[float, float, float],
        connector_orientation_deg: float,
        pull_threshold_n: float,
        wire_occurrence_id: str,
        wire_color_rgba: Tuple[float, float, float, float],
        overlay_events: List[WireRoutingOverlayEvent],
        board_surface_z: float,
        routed_segments: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] | None = None,
    ) -> Tuple[bool, ForceProfile]:
        builder = self._motion_builders[robot_name]
        base_transform = self._robot_base_transforms[robot_name]
        force_profile = ForceProfile()

        current_joints = state.current_joints
        current_time = state.current_time

        camera_offset = self._camera_service.computeInsertionOffset(
            connector_position, connector_orientation_deg,
        )

        normal_rad = math.radians(connector_orientation_deg)
        approach_dx = -math.cos(normal_rad) * self._config.insertion_approach_distance_m
        approach_dy = -math.sin(normal_rad) * self._config.insertion_approach_distance_m

        approach_position = (
            connector_position[0] + approach_dx + camera_offset.delta_x_m,
            connector_position[1] + approach_dy + camera_offset.delta_y_m,
            connector_position[2],
        )

        insertion_quat = _computeInsertionGraspQuat(connector_orientation_deg)

        transit_above = (approach_position[0], approach_position[1], approach_position[2] + 0.08)
        transit_pose = base_transform.transformPose(transit_above, insertion_quat)
        transit_joints = builder.computeJointAnglesForPose(
            robot_name, transit_pose, current_joints,
        )
        if transit_joints is None:
            return False, force_profile

        end_time = builder.queueMoveJ(
            robot_name, transit_joints, current_joints, current_time,
            description=f"WR insertion transit {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        approach_pose = base_transform.transformPose(approach_position, insertion_quat)
        approach_joints = builder.computeJointAnglesForPose(
            robot_name, approach_pose, transit_joints,
        )
        if approach_joints is None:
            return False, force_profile

        end_time, approach_joints = builder.queueMoveL(
            robot_name, approach_pose, transit_joints, current_time,
            duration_s=1.0,
            description=f"WR insertion approach {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        if state.last_peg_position is not None:
            final_segment = (state.last_peg_position, approach_position)
            if routed_segments is not None:
                routed_segments.append(final_segment)
            segment_id = f"{wire_occurrence_id}_seg_final_{state.extremity_index}"
            overlay_events.append(WireRoutingOverlayEvent(
                timestamp_s=current_time,
                event_type="ADD_ROUTED_SEGMENT",
                object_id=segment_id,
                object_type="routed_cable_segment",
                position_m=approach_position,
                robot_name=robot_name,
                color_rgba=wire_color_rgba,
                size_params={
                    "start_position_m": state.last_peg_position,
                    "end_position_m": approach_position,
                },
            ))

        insertion_target = (
            connector_position[0] + camera_offset.delta_x_m,
            connector_position[1] + camera_offset.delta_y_m,
            connector_position[2],
        )
        insertion_pose = base_transform.transformPose(insertion_target, insertion_quat)
        end_time, insert_joints = builder.queueMoveL(
            robot_name, insertion_pose, approach_joints, current_time,
            duration_s=1.5,
            description=f"WR insertion push {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        reading = self._ft_service.readForceTorque()
        force_profile.addReading(reading, current_time)

        regrasp_pos = (
            approach_position[0],
            approach_position[1],
            approach_position[2],
        )
        regrasp_pose = base_transform.transformPose(regrasp_pos, insertion_quat)
        end_time, regrasp_joints = builder.queueMoveL(
            robot_name, regrasp_pose, insert_joints, current_time,
            duration_s=0.5,
            description=f"WR regrasp retract {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        if not builder.queueGripper(robot_name, self._config.gripper_open_value, current_time):
            return False, force_profile
        current_time += self._config.gripper_settle_s

        if not builder.queueGripper(robot_name, self._config.gripper_close_value, current_time):
            return False, force_profile
        current_time += self._config.gripper_settle_s

        end_time, final_insert_joints = builder.queueMoveL(
            robot_name, insertion_pose, regrasp_joints, current_time,
            duration_s=1.0,
            description=f"WR insertion final {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        reading = self._ft_service.readForceTorque()
        force_profile.addReading(reading, current_time)
        is_complete = self._ft_service.isInsertionComplete(reading)

        if not is_complete:
            logger.warning(
                "Insertion force not reached for %s on %s -- continuing",
                wire_occurrence_id, robot_name,
            )

        pull_reading = self._ft_service.readForceTorque()
        force_profile.addReading(pull_reading, current_time + 0.5)
        pull_passed = self._ft_service.evaluatePullTest(pull_reading, pull_threshold_n)

        if not pull_passed:
            logger.error(
                "Pull test FAILED for %s on %s (threshold=%.1f N)",
                wire_occurrence_id, robot_name, pull_threshold_n,
            )
            return False, force_profile

        if not builder.queueGripper(robot_name, self._config.gripper_open_value, current_time + 0.5):
            return False, force_profile
        current_time += 1.0

        carried_id = f"{wire_occurrence_id}_carried_{state.extremity_index}"
        overlay_events.append(WireRoutingOverlayEvent(
            timestamp_s=current_time,
            event_type="REMOVE_CARRIED_CABLE",
            object_id=carried_id,
            object_type="carried_cable",
            robot_name=robot_name,
        ))

        retreat_pos = (
            approach_position[0],
            approach_position[1],
            approach_position[2] + 0.10,
        )
        retreat_pose = base_transform.transformPose(retreat_pos, _DEFAULT_GRASP_QUAT_WXYZ)
        end_time, retreat_joints = builder.queueMoveL(
            robot_name, retreat_pose, final_insert_joints, current_time,
            duration_s=1.0,
            description=f"WR insertion retreat {wire_occurrence_id}",
        )
        if end_time is None:
            return False, force_profile
        current_time = end_time

        self._coordinator.updateRobotTime(robot_name, current_time)
        state.current_joints = retreat_joints
        state.current_time = current_time

        return True, force_profile

    def _returnToHome(self, robot_name: str) -> None:
        builder = self._motion_builders[robot_name]
        home_joints = self._home_joints[robot_name]
        state = self._coordinator.getRobotState(robot_name)
        current_time = state.current_time_s

        end_time = builder.queueMoveJ(
            robot_name, home_joints, home_joints, current_time,
            description=f"WR return home {robot_name}",
        )
        if end_time is not None:
            self._coordinator.notifyAtHome(robot_name, end_time)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _findWireEndPickupConfig(
        self,
        wire_occurrence_id: str,
        extremity_index: int,
    ) -> Optional[WireEndPickupConfig]:
        for pickup_config in self._config.wire_end_pickups:
            if (
                pickup_config.wire_occurrence_id == wire_occurrence_id
                and pickup_config.extremity_index == extremity_index
            ):
                return pickup_config
        return None

    def _deriveCableAxisFromPegs(
        self,
        pickup_position: Tuple[float, float, float],
        peg_sequence: List[str],
        peg_positions_world: Dict[str, Tuple[float, float, float]],
    ) -> float:
        """Derive the cable axis orientation from the pickup-to-first-peg direction."""
        if not peg_sequence:
            return 0.0
        first_peg_pos = peg_positions_world.get(peg_sequence[0])
        if first_peg_pos is None:
            return 0.0
        delta_x = first_peg_pos[0] - pickup_position[0]
        delta_y = first_peg_pos[1] - pickup_position[1]
        if abs(delta_x) < 1e-9 and abs(delta_y) < 1e-9:
            return 0.0
        return math.degrees(math.atan2(delta_y, delta_x))

    def _resolvePullTestThreshold(self, cross_section_mm2: float) -> float:
        for threshold_config in self._config.pull_test_thresholds:
            if (
                threshold_config.min_cross_section_mm2
                <= cross_section_mm2
                < threshold_config.max_cross_section_mm2
            ):
                return threshold_config.threshold_force_n
        return 50.0

    def isSegmentClear(
        self,
        start_position: Tuple[float, float, float],
        end_position: Tuple[float, float, float],
        clearance_m: float = 0.02,
    ) -> bool:
        """Check whether a proposed cable segment is clear of already-routed segments."""
        for existing_start, existing_end in self._routed_segments:
            if _segmentsIntersectXY(
                start_position, end_position,
                existing_start, existing_end,
                clearance_m,
            ):
                return False
        return True


# ======================================================================
# Per-robot mutable state
# ======================================================================

@dataclass
class _RobotRoutingState:
    """Mutable per-robot state during a single wire routing execution."""
    robot_name: str
    extremity_index: int
    connector_id: str
    peg_sequence: List[str]
    pickup_position: Tuple[float, float, float]
    cable_axis_orientation_deg: float = 0.0
    anchor_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    current_joints: List[float] = field(default_factory=lambda: [0.0] * 6)
    current_time: float = 0.0
    last_peg_position: Optional[Tuple[float, float, float]] = None


# ======================================================================
# Geometry helpers
# ======================================================================

def _computePickupGraspQuat(
    cable_axis_orientation_deg: float,
) -> Tuple[float, float, float, float]:
    """Compute a top-down grasp quat with jaws perpendicular to the cable axis."""
    perpendicular_deg = cable_axis_orientation_deg + 90.0
    return composeZRotation(_DEFAULT_GRASP_QUAT_WXYZ, perpendicular_deg)


def _computeInsertionGraspQuat(
    connector_orientation_deg: float,
) -> Tuple[float, float, float, float]:
    """Compute a grasp quat for horizontal insertion along the connector normal.

    The gripper TCP is rotated so the approach direction aligns with
    the connector face normal.
    """
    return composeZRotation(_DEFAULT_GRASP_QUAT_WXYZ, connector_orientation_deg)


def _computePegSlotOffset(
    peg_orientation_deg: float,
    slot_offset_m: float,
) -> Tuple[float, float]:
    """Compute XY offset from peg center to the fork slot midpoint.

    The peg orientation is perpendicular to the cable direction.
    The slot opening is 90 deg from the crossbar, which means
    the slot is along the peg_orientation direction.
    We offset along the crossbar axis (perpendicular to the slot)
    so the cable passes between the prongs.
    """
    crossbar_rad = math.radians(peg_orientation_deg)
    offset_x = math.cos(crossbar_rad) * slot_offset_m
    offset_y = math.sin(crossbar_rad) * slot_offset_m
    return (offset_x, offset_y)


def _segmentsIntersectXY(
    start_a: Tuple[float, float, float],
    end_a: Tuple[float, float, float],
    start_b: Tuple[float, float, float],
    end_b: Tuple[float, float, float],
    clearance_m: float,
) -> bool:
    """Check whether two line segments in the XY plane are within clearance_m."""
    mid_a = ((start_a[0] + end_a[0]) / 2.0, (start_a[1] + end_a[1]) / 2.0)
    mid_b = ((start_b[0] + end_b[0]) / 2.0, (start_b[1] + end_b[1]) / 2.0)

    half_len_a = math.sqrt(
        (end_a[0] - start_a[0]) ** 2 + (end_a[1] - start_a[1]) ** 2,
    ) / 2.0
    half_len_b = math.sqrt(
        (end_b[0] - start_b[0]) ** 2 + (end_b[1] - start_b[1]) ** 2,
    ) / 2.0

    distance_between_mids = math.sqrt(
        (mid_a[0] - mid_b[0]) ** 2 + (mid_a[1] - mid_b[1]) ** 2,
    )

    return distance_between_mids < (half_len_a + half_len_b + clearance_m)
