"""
Generic motion-queueing utilities for robot arm control.

Provides reusable MoveJ, MoveL, and gripper queueing that both board
setup and future wire routing can consume via a hardware-protocol and
planner-client pair.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from simulation.interface.RobotHardwareProtocol import RobotHardwareInterface
from simulation.planning.MoveItPlannerClient import PlannerClient
from simulation.planning.PlanningModels import (
    MoveJRequest,
    MoveLRequest,
    PoseTarget,
)

logger = logging.getLogger(__name__)

DEFAULT_MOVEJ_DURATION_S = 2.0
DEFAULT_MOVEL_DURATION_S = 1.5


class MotionSequenceBuilder:
    """Queues MoveJ / MoveL / gripper commands via the hardware protocol."""

    def __init__(
        self,
        hardware: RobotHardwareInterface,
        planner: PlannerClient,
        movej_duration_s: float = DEFAULT_MOVEJ_DURATION_S,
        movel_duration_s: float = DEFAULT_MOVEL_DURATION_S,
    ) -> None:
        self.hardware = hardware
        self.planner = planner
        self.movej_duration_s = movej_duration_s
        self.movel_duration_s = movel_duration_s

    def queueMoveJ(
        self,
        robot_name: str,
        target_angles: List[float],
        start_angles: List[float],
        start_time_s: float,
        duration_s: float | None = None,
        description: str = "",
    ) -> Optional[float]:
        """Plan and queue a joint-space motion.

        Returns the end timestamp on success, ``None`` on planning failure.
        """
        actual_duration = duration_s if duration_s is not None else self.movej_duration_s
        if description:
            logger.info("  %s (t=%.1f)", description, start_time_s)

        request_data = MoveJRequest(
            robot_name=robot_name,
            target_joint_angles=target_angles,
            start_joint_angles=start_angles,
            duration_s=actual_duration,
        )
        planning_result = self.planner.plan_movej(request_data)
        if not planning_result.success:
            error_msg = (
                planning_result.planning_error.message
                if planning_result.planning_error else "unknown"
            )
            logger.error("    FAIL: MoveJ planning failed -- %s", error_msg)
            return None

        for point in planning_result.trajectory:
            command_ack = self.hardware.sendTimedSetpoint(
                robot_name=robot_name,
                timestamp_s=start_time_s + point.timestamp_s,
                joint_angles=point.joint_angles,
                gripper_command_value=point.gripper_command_value,
            )
            if not command_ack.accepted:
                logger.error(
                    "    FAIL: MoveJ setpoint rejected at t=%.3f -- %s",
                    start_time_s + point.timestamp_s,
                    command_ack.reason or "unknown",
                )
                return None

        return start_time_s + actual_duration

    def queueMoveL(
        self,
        robot_name: str,
        target_pose: PoseTarget,
        start_angles: List[float],
        start_time_s: float,
        duration_s: float | None = None,
        description: str = "",
    ) -> Tuple[Optional[float], List[float]]:
        """Plan and queue a Cartesian-space motion.

        Returns (end_timestamp, final_joint_angles) on success,
        or (None, start_angles) on planning failure.
        """
        actual_duration = duration_s if duration_s is not None else self.movel_duration_s
        if description:
            logger.info("  %s (t=%.1f)", description, start_time_s)

        request_data = MoveLRequest(
            robot_name=robot_name,
            target_pose=target_pose,
            start_joint_angles=start_angles,
            duration_s=actual_duration,
        )
        planning_result = self.planner.plan_movel(request_data)
        if not planning_result.success:
            error_msg = (
                planning_result.planning_error.message
                if planning_result.planning_error else "unknown"
            )
            logger.error("    FAIL: MoveL planning failed -- %s", error_msg)
            return None, start_angles

        for point in planning_result.trajectory:
            command_ack = self.hardware.sendTimedSetpoint(
                robot_name=robot_name,
                timestamp_s=start_time_s + point.timestamp_s,
                joint_angles=point.joint_angles,
                gripper_command_value=point.gripper_command_value,
            )
            if not command_ack.accepted:
                logger.error(
                    "    FAIL: MoveL setpoint rejected at t=%.3f -- %s",
                    start_time_s + point.timestamp_s,
                    command_ack.reason or "unknown",
                )
                return None, start_angles

        final_angles = list(planning_result.trajectory[-1].joint_angles)
        return start_time_s + actual_duration, final_angles

    def queueGripper(
        self,
        robot_name: str,
        gripper_value: float,
        timestamp_s: float,
    ) -> bool:
        """Queue a gripper command at the given timestamp."""
        command_ack = self.hardware.sendTimedSetpoint(
            robot_name=robot_name,
            timestamp_s=timestamp_s,
            gripper_command_value=gripper_value,
        )
        if not command_ack.accepted:
            logger.error(
                "    FAIL: Gripper setpoint rejected at t=%.3f -- %s",
                timestamp_s,
                command_ack.reason or "unknown",
            )
            return False
        return True

    def computeJointAnglesForPose(
        self,
        robot_name: str,
        target_pose: PoseTarget,
        seed_angles: List[float],
    ) -> Optional[List[float]]:
        """Solve IK for *target_pose* without queueing any motion."""
        movel_request = MoveLRequest(
            robot_name=robot_name,
            target_pose=target_pose,
            start_joint_angles=seed_angles,
            duration_s=self.movel_duration_s,
        )
        plan_result = self.planner.plan_movel(movel_request)
        if plan_result.success and plan_result.trajectory:
            return list(plan_result.trajectory[-1].joint_angles)
        logger.error("    FAIL: IK computation failed for pose")
        return None
