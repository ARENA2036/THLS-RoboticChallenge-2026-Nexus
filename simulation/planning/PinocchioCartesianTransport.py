"""
Planning transport backed by Pinocchio IK and Cartesian path interpolation.

Implements the MoveItPlanningTransport protocol so it can be used as a
drop-in replacement for LocalMockMoveItTransport.

  plan_movej  – joint-space linear interpolation (no IK needed).
  plan_movel  – Cartesian LERP+SLERP path, each waypoint solved by DLS IK.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pinocchio as pin

from simulation.planning.CartesianPathPlanner import planCartesianPath
from simulation.planning.ForwardKinematicsProtocol import RobotBodyPoints
from simulation.planning.PinocchioIkSolver import PinocchioIkSolver, IkParameters
from simulation.planning.PlanningModels import (
    MoveJRequest,
    MoveLRequest,
    MotionType,
    PlanningError,
    PlanningResult,
    TimedJointPoint,
)

logger = logging.getLogger(__name__)

_DEFAULT_HOME_JOINT_ANGLES = [0.0, -1.5708, 1.5708, -1.5708, -1.5708, 0.0]
DEFAULT_CARTESIAN_WAYPOINTS = 50


class PinocchioCartesianTransport:
    """
    Real planning transport using Pinocchio FK/IK and Cartesian interpolation.

    One solver instance per robot is created lazily so the same transport
    can serve both left and right arms.
    """

    def __init__(
        self,
        urdf_path: Optional[str] = None,
        ik_parameters: Optional[IkParameters] = None,
        num_cartesian_waypoints: int = DEFAULT_CARTESIAN_WAYPOINTS,
        home_joint_angles: Optional[List[float]] = None,
    ) -> None:
        self.ik_solver_ = PinocchioIkSolver(
            urdf_path=urdf_path,
            ik_parameters=ik_parameters,
        )
        self.num_cartesian_waypoints_ = num_cartesian_waypoints
        self.home_joint_angles_ = list(home_joint_angles or _DEFAULT_HOME_JOINT_ANGLES)

    BODY_FRAME_NAMES = [
        "upper_arm_link",
        "forearm_link",
        "wrist_1_link",
        "wrist_2_link",
        "tcp_frame",
    ]
    BODY_POINT_LABELS = ["elbow", "forearm_mid", "wrist", "flange", "tcp"]

    def computeTcpPosition(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        """Return the TCP position in robot-base frame for the given joint angles."""
        joint_array = np.array(joint_angles, dtype=float)
        tcp_se3 = self.ik_solver_.computeForwardKinematics(joint_array)
        pos = tcp_se3.translation
        return (float(pos[0]), float(pos[1]), float(pos[2]))

    def compute_tcp_position(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        """Legacy alias -- delegates to computeTcpPosition."""
        return self.computeTcpPosition(joint_angles)

    def computeBodyPoints(self, joint_angles: List[float]) -> RobotBodyPoints:
        """Return positions for 5 representative points along the kinematic chain.

        Uses a single FK call.  The forearm midpoint is interpolated between
        forearm_link and wrist_1_link origins.
        """
        joint_array = np.array(joint_angles, dtype=float)
        frame_positions = self.ik_solver_.computeMultiFrameFK(
            joint_array, self.BODY_FRAME_NAMES,
        )

        forearm_pos = frame_positions.get("forearm_link", (0.0, 0.0, 0.0))
        wrist1_pos = frame_positions.get("wrist_1_link", (0.0, 0.0, 0.0))
        forearm_mid = (
            (forearm_pos[0] + wrist1_pos[0]) / 2.0,
            (forearm_pos[1] + wrist1_pos[1]) / 2.0,
            (forearm_pos[2] + wrist1_pos[2]) / 2.0,
        )

        points = [
            frame_positions.get("upper_arm_link", (0.0, 0.0, 0.0)),
            forearm_mid,
            frame_positions.get("wrist_2_link", (0.0, 0.0, 0.0)),
            frame_positions.get("wrist_2_link", (0.0, 0.0, 0.0)),
            frame_positions.get("tcp_frame", (0.0, 0.0, 0.0)),
        ]

        return RobotBodyPoints(points=points, labels=list(self.BODY_POINT_LABELS))

    # ------------------------------------------------------------------
    # MoveItPlanningTransport protocol
    # ------------------------------------------------------------------

    def plan_movej(self, request_data: MoveJRequest) -> PlanningResult:
        start_joint_angles = (
            request_data.start_joint_angles
            or self.home_joint_angles_
        )
        trajectory = _interpolate_joint_trajectory(
            start_joint_angles=start_joint_angles,
            target_joint_angles=request_data.target_joint_angles,
            duration_s=request_data.duration_s,
        )
        return PlanningResult(
            motion_type=MotionType.MOVEJ,
            robot_name=request_data.robot_name,
            success=True,
            trajectory=trajectory,
        )

    def plan_movel(self, request_data: MoveLRequest) -> PlanningResult:
        start_joint_angles = np.array(
            request_data.start_joint_angles or self.home_joint_angles_,
            dtype=float,
        )

        start_pose = self.ik_solver_.computeForwardKinematics(start_joint_angles)

        target_position = np.array(request_data.target_pose.position_m, dtype=float)
        target_quat_wxyz = np.array(request_data.target_pose.quat_wxyz, dtype=float)
        target_pose = _pose_target_to_se3(target_position, target_quat_wxyz)

        cartesian_result = planCartesianPath(
            start_pose=start_pose,
            target_pose=target_pose,
            duration_s=request_data.duration_s,
            num_waypoints=self.num_cartesian_waypoints_,
        )

        trajectory: List[TimedJointPoint] = []
        current_joint_angles = start_joint_angles.copy()

        for waypoint in cartesian_result.waypoints:
            ik_result = self.ik_solver_.computeInverseKinematics(
                target_pose=waypoint.pose,
                initial_joint_angles=current_joint_angles,
            )

            if not ik_result.converged:
                logger.warning(
                    "IK did not converge at t=%.3fs (pos_err=%.2e, ori_err=%.2e)",
                    waypoint.timestamp_s,
                    ik_result.position_error,
                    ik_result.orientation_error,
                )
                return PlanningResult(
                    motion_type=MotionType.MOVEL,
                    robot_name=request_data.robot_name,
                    success=False,
                    trajectory=trajectory,
                    planning_error=PlanningError(
                        code="IK_FAILED",
                        message=(
                            f"IK did not converge at t={waypoint.timestamp_s:.3f}s. "
                            f"pos_err={ik_result.position_error:.2e}, "
                            f"ori_err={ik_result.orientation_error:.2e}"
                        ),
                    ),
                )

            current_joint_angles = ik_result.joint_angles
            trajectory.append(
                TimedJointPoint(
                    timestamp_s=waypoint.timestamp_s,
                    joint_angles=current_joint_angles.tolist(),
                )
            )

        return PlanningResult(
            motion_type=MotionType.MOVEL,
            robot_name=request_data.robot_name,
            success=True,
            trajectory=trajectory,
        )

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _pose_target_to_se3(position: np.ndarray, quat_wxyz: np.ndarray) -> pin.SE3:
    """Convert position + quaternion (w, x, y, z) to a Pinocchio SE3."""
    quat_xyzw = np.array([quat_wxyz[1], quat_wxyz[2], quat_wxyz[3], quat_wxyz[0]])
    rotation = pin.Quaternion(quat_xyzw).toRotationMatrix()
    return pin.SE3(rotation, position)


def _interpolate_joint_trajectory(
    start_joint_angles: list[float],
    target_joint_angles: list[float],
    duration_s: float,
    sample_count: int = 50,
) -> list[TimedJointPoint]:
    trajectory: list[TimedJointPoint] = []
    for sample_index in range(sample_count):
        interpolation_ratio = sample_index / max(sample_count - 1, 1)
        timestamp_s = interpolation_ratio * duration_s
        joint_angles = [
            start_value + interpolation_ratio * (target_value - start_value)
            for start_value, target_value in zip(start_joint_angles, target_joint_angles)
        ]
        trajectory.append(
            TimedJointPoint(timestamp_s=timestamp_s, joint_angles=joint_angles)
        )
    return trajectory
