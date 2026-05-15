"""
Board setup executor -- pre-queues pick-and-place setpoints for viewer replay.

Supports **parallel two-robot execution** with workspace coordination:
  - Pickup zone: exclusive access (one robot at a time).
  - Board halves: a robot enters the other's half only when the other is at home.
  - Transport height: objects are lifted above the board during MoveJ transfers.

Delegates motion queueing to MotionSequenceBuilder and collision checking
to the TrajectoryCollisionChecker (or its own legacy TCP-only check).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Dict, List, Optional, Tuple

import numpy as np

from simulation.core.ConfigModels import BoardSetupConfig
from simulation.core.CoordinateTransform import WorldToRobotBaseTransform
from simulation.interface.RobotHardwareProtocol import RobotHardwareInterface
from simulation.planning.LayoutToSimulationBridge import BoardSetupMotionPlan
from simulation.planning.MoveItPlannerClient import PlannerClient
from simulation.planning.MotionSequenceBuilder import MotionSequenceBuilder
from simulation.planning.PlanningModels import PoseTarget
from simulation.planning.SafetyPolicy import SafetyPolicy
from simulation.planning.TrajectoryCollisionChecker import (
    SharedAreaPolicy,
    TrajectoryCollisionChecker,
)
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator

logger = logging.getLogger(__name__)

_DEFAULT_HOME_JOINT_ANGLES = [0.0, -1.57, 1.57, -1.57, -1.57, 0.0]


class OverlayEventType(StrEnum):
    ADD_CARRIED = "ADD_CARRIED"
    PLACE_OBJECT = "PLACE_OBJECT"


@dataclass
class OverlayEvent:
    timestamp_s: float
    event_type: OverlayEventType
    object_id: str
    object_type: str
    position_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    robot_name: str = ""
    orientation_deg: float = 0.0


@dataclass
class BoardSetupResult:
    success: bool
    completed_steps: int
    total_steps: int
    total_duration_s: float = 0.0
    overlay_events: List[OverlayEvent] = field(default_factory=list)
    failed_step_id: Optional[str] = None
    failure_message: Optional[str] = None


class BoardSetupExecutor:
    """Pre-plans and queues all pick-and-place motions for board setup.

    Composes MotionSequenceBuilder for queueing and WorkspaceCoordinator
    for scheduling.  The pick-and-place sequence logic stays here.
    """

    def __init__(
        self,
        hardware_interface: RobotHardwareInterface,
        planner_client: PlannerClient,
        workspace_coordinator: WorkspaceCoordinator,
        robot_base_transforms: Dict[str, WorldToRobotBaseTransform] | None = None,
        home_joint_angles: List[float] | None = None,
        home_joint_angles_by_robot: Dict[str, List[float]] | None = None,
        trajectory_collision_checker: TrajectoryCollisionChecker | None = None,
        shared_area_policy: SharedAreaPolicy | None = None,
        wait_poll_interval_s: float = 0.2,
        board_setup_config: BoardSetupConfig | None = None,
    ) -> None:
        self.hardware_interface = hardware_interface
        self.planner_client = planner_client
        self.coordinator = workspace_coordinator
        self.robot_base_transforms = robot_base_transforms or {}
        self.home_joint_angles = list(home_joint_angles or _DEFAULT_HOME_JOINT_ANGLES)
        self._home_joint_angles_by_robot: Dict[str, List[float]] = {}
        if home_joint_angles_by_robot is not None:
            for robot_name, joint_angles in home_joint_angles_by_robot.items():
                self._home_joint_angles_by_robot[robot_name] = list(joint_angles)
        self.trajectory_collision_checker = trajectory_collision_checker
        self.shared_area_policy = shared_area_policy
        self.wait_poll_interval_s = wait_poll_interval_s

        config = board_setup_config or BoardSetupConfig()
        self._gripper_open = config.gripper_open_value
        self._gripper_close = config.gripper_close_value
        self._gripper_settle_s = config.gripper_settle_s
        self._clearance_num_samples = config.clearance_num_samples

        self._motion_builder = MotionSequenceBuilder(
            hardware=hardware_interface,
            planner=planner_client,
        )

    def prequeuePlans(
        self,
        motion_plans: List[BoardSetupMotionPlan],
    ) -> BoardSetupResult:
        total_steps = len(motion_plans)
        logger.info("Pre-planning board setup: %d objects to place", total_steps)

        pending_plans: Dict[str, List[BoardSetupMotionPlan]] = {}
        for plan in motion_plans:
            pending_plans.setdefault(plan.robot_name, []).append(plan)

        last_joint_target: Dict[str, List[float]] = {}
        for robot_name in self.hardware_interface.robot_names:
            last_joint_target[robot_name] = self.getHomeJointAngles(robot_name)
            self.coordinator.notifyAtHome(robot_name, 0.0)

        overlay_events: List[OverlayEvent] = []
        completed_steps = 0
        plan_counter = 0

        while True:
            next_robot = self.coordinator.selectNextRobot(pending_plans)
            if next_robot is None:
                break

            plan = pending_plans[next_robot].pop(0)
            plan_counter += 1
            step_label = f"[{plan_counter}/{total_steps}]"
            logger.info(
                "%s Planning %s '%s' with robot '%s'",
                step_label, plan.object_type, plan.object_id, plan.robot_name,
            )

            success = self._prequeueSinglePlacement(
                plan, step_label, last_joint_target, overlay_events,
            )

            if not success:
                logger.error("%s FAILED at step '%s'", step_label, plan.step_id)
                total_duration = max(
                    self.coordinator.getRobotState(r).current_time_s
                    for r in self.hardware_interface.robot_names
                )
                return BoardSetupResult(
                    success=False,
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                    total_duration_s=total_duration,
                    overlay_events=overlay_events,
                    failed_step_id=plan.step_id,
                    failure_message=f"Planning failed for {plan.object_type} '{plan.object_id}'",
                )

            completed_steps += 1

        total_duration = max(
            self.coordinator.getRobotState(r).current_time_s
            for r in self.hardware_interface.robot_names
        )
        logger.info(
            "Pre-planning complete: %d steps, %.1f s total",
            total_steps, total_duration,
        )
        return BoardSetupResult(
            success=True,
            completed_steps=total_steps,
            total_steps=total_steps,
            total_duration_s=total_duration,
            overlay_events=overlay_events,
        )

    def _waitForTrajectoryClearance(
        self,
        robot_name: str,
        start_angles: List[float],
        end_angles: List[float],
        candidate_start_s: float,
        duration_s: float,
    ) -> Optional[float]:
        if self.trajectory_collision_checker is None:
            return candidate_start_s
        trajectory_store = self.coordinator.trajectory_store
        if trajectory_store is None:
            return candidate_start_s

        other_robot_name = self.coordinator.getOtherRobotName(robot_name)
        scheduled_start_s = candidate_start_s
        for _ in range(self.coordinator.max_retry_count):
            clearance_result = self.trajectory_collision_checker.isPathClearOfTrajectory(
                robot_name=robot_name,
                start_angles=start_angles,
                end_angles=end_angles,
                motion_start_s=scheduled_start_s,
                motion_end_s=scheduled_start_s + duration_s,
                other_robot_name=other_robot_name,
                trajectory_store=trajectory_store,
                shared_area_policy=self.shared_area_policy,
            )
            if clearance_result.is_clear:
                return scheduled_start_s

            if self.coordinator.safety_policy == SafetyPolicy.ABORT_ON_CONFLICT:
                logger.error(
                    "    Abort on trajectory conflict: %s/%s dist=%.3fm at t=%.2fs",
                    clearance_result.closest_point_pair[0],
                    clearance_result.closest_point_pair[1],
                    clearance_result.minimum_distance_m,
                    clearance_result.closest_time_s,
                )
                return None

            scheduled_start_s += self.wait_poll_interval_s
            if scheduled_start_s - candidate_start_s > self.coordinator.max_wait_time_s:
                logger.error(
                    "    Waited %.1fs for inter-robot clearance, giving up",
                    self.coordinator.max_wait_time_s,
                )
                return None

        logger.error(
            "    Exceeded %d retries while waiting for inter-robot clearance",
            self.coordinator.max_retry_count,
        )
        return None

    def _queueMoveJWithSafety(
        self,
        robot_name: str,
        target_angles: List[float],
        start_angles: List[float],
        start_time_s: float,
        description: str,
        duration_s: float | None = None,
    ) -> Optional[float]:
        builder = self._motion_builder
        actual_duration_s = duration_s if duration_s is not None else builder.movej_duration_s
        safe_start_s = self._waitForTrajectoryClearance(
            robot_name=robot_name,
            start_angles=start_angles,
            end_angles=target_angles,
            candidate_start_s=start_time_s,
            duration_s=actual_duration_s,
        )
        if safe_start_s is None:
            return None
        if safe_start_s > start_time_s:
            logger.info(
                "    %s waits %.1fs for trajectory clearance",
                robot_name,
                safe_start_s - start_time_s,
            )
        end_time_s = builder.queueMoveJ(
            robot_name=robot_name,
            target_angles=target_angles,
            start_angles=start_angles,
            start_time_s=safe_start_s,
            duration_s=duration_s,
            description=description,
        )
        if end_time_s is None:
            return None
        self.coordinator.registerMotionSegment(
            robot_name=robot_name,
            start_time_s=safe_start_s,
            end_time_s=end_time_s,
            start_angles=start_angles,
            end_angles=target_angles,
        )
        return end_time_s

    def _queueMoveLWithSafety(
        self,
        robot_name: str,
        target_pose: PoseTarget,
        start_angles: List[float],
        start_time_s: float,
        description: str,
        duration_s: float | None = None,
    ) -> Tuple[Optional[float], List[float]]:
        builder = self._motion_builder
        predicted_end_angles = builder.computeJointAnglesForPose(
            robot_name=robot_name,
            target_pose=target_pose,
            seed_angles=start_angles,
        )
        if predicted_end_angles is None:
            return None, start_angles

        actual_duration_s = duration_s if duration_s is not None else builder.movel_duration_s
        safe_start_s = self._waitForTrajectoryClearance(
            robot_name=robot_name,
            start_angles=start_angles,
            end_angles=predicted_end_angles,
            candidate_start_s=start_time_s,
            duration_s=actual_duration_s,
        )
        if safe_start_s is None:
            return None, start_angles
        if safe_start_s > start_time_s:
            logger.info(
                "    %s waits %.1fs for trajectory clearance",
                robot_name,
                safe_start_s - start_time_s,
            )

        end_time_s, final_angles = builder.queueMoveL(
            robot_name=robot_name,
            target_pose=target_pose,
            start_angles=start_angles,
            start_time_s=safe_start_s,
            duration_s=duration_s,
            description=description,
        )
        if end_time_s is None:
            return None, start_angles
        self.coordinator.registerMotionSegment(
            robot_name=robot_name,
            start_time_s=safe_start_s,
            end_time_s=end_time_s,
            start_angles=start_angles,
            end_angles=final_angles,
        )
        return end_time_s, final_angles

    def executeStep(
        self,
        plan: BoardSetupMotionPlan,
        last_joint_target: Dict[str, List[float]],
        overlay_events: List[OverlayEvent],
        step_label: str = "",
    ) -> bool:
        """Execute a single planning step via the same prequeue path."""
        if not step_label:
            step_label = "[reactive]"
        return self._prequeueSinglePlacement(
            plan=plan,
            step_label=step_label,
            last_joint_target=last_joint_target,
            overlay_events=overlay_events,
        )

    def getHomeJointAngles(self, robot_name: str) -> List[float]:
        if robot_name in self._home_joint_angles_by_robot:
            return list(self._home_joint_angles_by_robot[robot_name])
        return list(self.home_joint_angles)

    def _computeTcpWorldPosition(
        self,
        robot_name: str,
        joint_angles: List[float],
    ) -> Tuple[float, float, float]:
        tcp_robot_base = self.planner_client.compute_tcp_position(joint_angles)
        base_tf = self.robot_base_transforms.get(robot_name)
        if base_tf is None:
            return tcp_robot_base
        return base_tf.inverseTransformPosition(tcp_robot_base)

    def _isPathClearOfPickup(
        self,
        robot_name: str,
        start_angles: List[float],
        end_angles: List[float],
        pickup_center_world_m: Tuple[float, float, float],
    ) -> Tuple[bool, float]:
        clearance_radius_m = self.coordinator.pickup_clearance_radius_m
        if self.trajectory_collision_checker is not None:
            clearance_result = self.trajectory_collision_checker.isPathClearOfZone(
                robot_name=robot_name,
                start_angles=start_angles,
                end_angles=end_angles,
                zone_center_world=pickup_center_world_m,
                clearance_radius=clearance_radius_m,
                num_samples=self._clearance_num_samples,
            )
            return clearance_result.is_clear, clearance_result.minimum_distance_m

        pickup_center = np.array(pickup_center_world_m, dtype=np.float64)
        start_arr = np.array(start_angles, dtype=np.float64)
        end_arr = np.array(end_angles, dtype=np.float64)

        minimum_distance = float("inf")
        for sample_index in range(self._clearance_num_samples + 1):
            alpha = sample_index / self._clearance_num_samples
            interpolated_angles = list(start_arr + alpha * (end_arr - start_arr))
            tcp_world = np.array(
                self._computeTcpWorldPosition(robot_name, interpolated_angles),
                dtype=np.float64,
            )
            distance = float(np.linalg.norm(tcp_world - pickup_center))
            minimum_distance = min(minimum_distance, distance)

        is_all_clear = minimum_distance >= clearance_radius_m
        return is_all_clear, minimum_distance

    def _prequeueSinglePlacement(
        self,
        plan: BoardSetupMotionPlan,
        step_label: str,
        last_joint_target: Dict[str, List[float]],
        overlay_events: List[OverlayEvent],
    ) -> bool:
        robot_name = plan.robot_name
        robot_state = self.coordinator.getRobotState(robot_name)
        current_time = robot_state.current_time_s
        builder = self._motion_builder

        robot_home_joint_angles = self.getHomeJointAngles(robot_name)

        time_after = self._queueMoveJWithSafety(
            robot_name, robot_home_joint_angles,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveJ -> home",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = list(robot_home_joint_angles)
        self.coordinator.notifyAtHome(robot_name, current_time)

        staging_pose = self._computeStagingPose(
            robot_name, plan.pickup_world_m, plan.pickup_approach_pose,
            last_joint_target[robot_name],
        )
        if staging_pose is not None:
            staging_angles = builder.computeJointAnglesForPose(
                robot_name, staging_pose, last_joint_target[robot_name],
            )
            if staging_angles is not None:
                time_after = self._queueMoveJWithSafety(
                    robot_name, staging_angles,
                    last_joint_target[robot_name], current_time,
                    description=f"{step_label} MoveJ -> staging (near pickup boundary)",
                )
                if time_after is not None:
                    current_time = time_after
                    last_joint_target[robot_name] = staging_angles

        pickup_start = self.coordinator.acquirePickupZone(robot_name)
        if pickup_start > current_time:
            logger.info("    %s waits %.1fs for pickup zone (at staging)", robot_name, pickup_start - current_time)
            current_time = pickup_start
        self.coordinator.notifyZoneEntered(robot_name, current_time)

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.pickup_approach_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> pickup approach",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.pickup_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> pickup",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        if not builder.queueGripper(robot_name, self._gripper_close, current_time):
            return False
        current_time += self._gripper_settle_s

        overlay_events.append(OverlayEvent(
            timestamp_s=current_time,
            event_type=OverlayEventType.ADD_CARRIED,
            object_id=plan.object_id,
            object_type=plan.object_type,
            position_m=plan.pickup_world_m,
            robot_name=robot_name,
            orientation_deg=plan.pickup_orientation_deg,
        ))

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.pickup_retreat_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> pickup retreat",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        transport_angles = builder.computeJointAnglesForPose(
            robot_name, plan.pickup_transport_pose, last_joint_target[robot_name],
        )
        if transport_angles is None:
            return False
        time_after = self._queueMoveJWithSafety(
            robot_name, transport_angles,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveJ -> transport height (pickup)",
        )
        if time_after is None:
            return False
        current_time = time_after
        prev_angles_for_clearance = list(last_joint_target[robot_name])
        last_joint_target[robot_name] = transport_angles

        zone_released = self._tryReleasePickupZone(
            robot_name, prev_angles_for_clearance, transport_angles,
            plan.pickup_world_m, current_time,
            f"{step_label} transport(pickup)",
        )

        board_half_start = self.coordinator.acquireBoardHalf(
            robot_name, plan.placement_world_m[0],
        )
        if board_half_start > current_time:
            current_time = board_half_start
        self.coordinator.updateRobotTime(robot_name, current_time)

        placement_transport_angles = builder.computeJointAnglesForPose(
            robot_name, plan.placement_transport_pose, last_joint_target[robot_name],
        )
        if placement_transport_angles is None:
            return False
        time_after = self._queueMoveJWithSafety(
            robot_name, placement_transport_angles,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveJ -> transport height (placement)",
        )
        if time_after is None:
            return False
        current_time = time_after
        prev_angles_for_clearance = list(last_joint_target[robot_name])
        last_joint_target[robot_name] = placement_transport_angles

        if not zone_released:
            zone_released = self._tryReleasePickupZone(
                robot_name, prev_angles_for_clearance, placement_transport_angles,
                plan.pickup_world_m, current_time,
                f"{step_label} transport(placement)",
            )

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.placement_approach_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> placement approach",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        if not zone_released:
            tcp_world = self._computeTcpWorldPosition(robot_name, final_angles)
            distance = float(np.linalg.norm(
                np.array(tcp_world) - np.array(plan.pickup_world_m),
            ))
            if distance >= self.coordinator.pickup_clearance_radius_m:
                logger.info(
                    "    Pickup zone released after placement approach (%.2fm >= %.2fm)",
                    distance, self.coordinator.pickup_clearance_radius_m,
                )
                self.coordinator.releasePickupZone(robot_name, current_time)
                self.coordinator.notifyZoneExited(robot_name, current_time)
                zone_released = True

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.placement_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> placement",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        overlay_events.append(OverlayEvent(
            timestamp_s=current_time,
            event_type=OverlayEventType.PLACE_OBJECT,
            object_id=plan.object_id,
            object_type=plan.object_type,
            position_m=plan.placement_world_m,
            robot_name=robot_name,
            orientation_deg=plan.placement_orientation_deg,
        ))

        if not builder.queueGripper(robot_name, self._gripper_open, current_time):
            return False
        current_time += self._gripper_settle_s

        time_after, final_angles = self._queueMoveLWithSafety(
            robot_name, plan.placement_retreat_pose,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveL -> retreat",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = final_angles

        time_after = self._queueMoveJWithSafety(
            robot_name, robot_home_joint_angles,
            last_joint_target[robot_name], current_time,
            description=f"{step_label} MoveJ -> home (clear)",
        )
        if time_after is None:
            return False
        current_time = time_after
        last_joint_target[robot_name] = list(robot_home_joint_angles)
        self.coordinator.notifyAtHome(robot_name, current_time)

        if not zone_released:
            logger.info("    Pickup zone released at home (fallback)")
            self.coordinator.releasePickupZone(robot_name, current_time)
            self.coordinator.notifyZoneExited(robot_name, current_time)

        return True

    def _computeStagingPose(
        self,
        robot_name: str,
        pickup_world_m: Tuple[float, float, float],
        pickup_approach_pose: PoseTarget,
        current_joint_angles: List[float],
    ) -> Optional[PoseTarget]:
        tcp_world = np.array(
            self._computeTcpWorldPosition(robot_name, current_joint_angles),
            dtype=np.float64,
        )
        pickup_center = np.array(pickup_world_m, dtype=np.float64)
        direction = tcp_world - pickup_center
        horizontal_distance = float(np.linalg.norm(direction[:2]))
        pickup_clearance_radius_m = self.coordinator.pickup_clearance_radius_m

        if horizontal_distance < pickup_clearance_radius_m:
            return None

        direction_xy = np.array([direction[0], direction[1], 0.0], dtype=np.float64)
        direction_xy_normalised = direction_xy / np.linalg.norm(direction_xy[:2])
        staging_world = pickup_center + direction_xy_normalised * pickup_clearance_radius_m
        staging_world[2] = tcp_world[2]

        base_tf = self.robot_base_transforms.get(robot_name)
        if base_tf is None:
            return None

        grasp_quat = tuple(pickup_approach_pose.quat_wxyz)
        staging_world_tuple = (float(staging_world[0]), float(staging_world[1]), float(staging_world[2]))
        return base_tf.transformPose(staging_world_tuple, grasp_quat)

    def _tryReleasePickupZone(
        self,
        robot_name: str,
        start_angles: List[float],
        end_angles: List[float],
        pickup_world_m: Tuple[float, float, float],
        release_time_s: float,
        description: str,
    ) -> bool:
        is_clear, minimum_distance = self._isPathClearOfPickup(
            robot_name, start_angles, end_angles, pickup_world_m,
        )
        if is_clear:
            logger.info(
                "    Pickup zone released after %s (min TCP dist %.2fm >= %.2fm)",
                description, minimum_distance, self.coordinator.pickup_clearance_radius_m,
            )
            self.coordinator.releasePickupZone(robot_name, release_time_s)
            self.coordinator.notifyZoneExited(robot_name, release_time_s)
            return True

        logger.info(
            "    Pickup zone NOT released after %s (min TCP dist %.2fm < %.2fm)",
            description, minimum_distance, self.coordinator.pickup_clearance_radius_m,
        )
        return False
