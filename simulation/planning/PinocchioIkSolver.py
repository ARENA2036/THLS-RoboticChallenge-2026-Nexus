"""
Pinocchio-based forward and inverse kinematics solver.

Wraps a Pinocchio model loaded from the UR10e + Robotiq 2F-85 URDF.
Provides FK and damped-least-squares (DLS) 6-DOF IK targeting the TCP frame.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pinocchio as pin


NUM_JOINTS = 6

_DEFAULT_URDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "models", "ur10e_robotiq2f85.urdf"
)


@dataclass
class IkParameters:
    """Tuning knobs for the DLS IK solver."""
    damping_factor: float = 1e-6
    max_iterations: int = 1000
    position_tolerance: float = 1e-4
    orientation_tolerance: float = 1e-4
    step_size: float = 1.0


@dataclass
class IkResult:
    """Return value of the IK solver."""
    converged: bool
    joint_angles: np.ndarray
    position_error: float
    orientation_error: float
    iterations_used: int


class PinocchioIkSolver:
    """FK / IK for a single UR10e + Robotiq 2F-85 arm."""

    def __init__(
        self,
        urdf_path: Optional[str] = None,
        tcp_frame_name: str = "tcp_frame",
        ik_parameters: Optional[IkParameters] = None,
    ) -> None:
        resolved_path = os.path.abspath(urdf_path or _DEFAULT_URDF_PATH)
        self.model_ = pin.buildModelFromUrdf(resolved_path)
        self.data_ = self.model_.createData()
        self.tcp_frame_id_ = self.model_.getFrameId(tcp_frame_name)
        if self.tcp_frame_id_ >= self.model_.nframes:
            raise ValueError(
                f"Frame '{tcp_frame_name}' not found in URDF. "
                f"Available: {[self.model_.frames[i].name for i in range(self.model_.nframes)]}"
            )
        self.ik_parameters_ = ik_parameters or IkParameters()

    # ------------------------------------------------------------------
    # Forward kinematics
    # ------------------------------------------------------------------

    def computeForwardKinematics(self, joint_angles: np.ndarray) -> pin.SE3:
        """Return the TCP pose (SE3) for the given joint configuration."""
        assert joint_angles.shape == (NUM_JOINTS,), (
            f"Expected {NUM_JOINTS} joint values, got {joint_angles.shape}"
        )
        pin.forwardKinematics(self.model_, self.data_, joint_angles)
        pin.updateFramePlacements(self.model_, self.data_)
        return self.data_.oMf[self.tcp_frame_id_].copy()

    def computeMultiFrameFK(
        self,
        joint_angles: np.ndarray,
        frame_names: List[str],
    ) -> Dict[str, Tuple[float, float, float]]:
        """Return positions for multiple named frames in a single FK call."""
        assert joint_angles.shape == (NUM_JOINTS,), (
            f"Expected {NUM_JOINTS} joint values, got {joint_angles.shape}"
        )
        pin.forwardKinematics(self.model_, self.data_, joint_angles)
        pin.updateFramePlacements(self.model_, self.data_)

        result: Dict[str, Tuple[float, float, float]] = {}
        for frame_name in frame_names:
            frame_id = self.model_.getFrameId(frame_name)
            if frame_id < self.model_.nframes:
                pos = self.data_.oMf[frame_id].translation
                result[frame_name] = (float(pos[0]), float(pos[1]), float(pos[2]))
        return result

    # ------------------------------------------------------------------
    # Inverse kinematics (damped least squares)
    # ------------------------------------------------------------------

    def computeInverseKinematics(
        self,
        target_pose: pin.SE3,
        initial_joint_angles: np.ndarray,
    ) -> IkResult:
        """
        Solve 6-DOF IK via damped-least-squares iteration.

        Returns an IkResult indicating convergence, final joint angles, and errors.
        """
        joint_angles = initial_joint_angles.copy()
        params = self.ik_parameters_

        identity_damping = params.damping_factor * np.eye(6)

        for iteration_index in range(params.max_iterations):
            pin.forwardKinematics(self.model_, self.data_, joint_angles)
            pin.updateFramePlacements(self.model_, self.data_)

            current_pose = self.data_.oMf[self.tcp_frame_id_]
            error_twist = pin.log6(current_pose.actInv(target_pose)).vector

            position_error = float(np.linalg.norm(error_twist[:3]))
            orientation_error = float(np.linalg.norm(error_twist[3:]))

            if (
                position_error < params.position_tolerance
                and orientation_error < params.orientation_tolerance
            ):
                return IkResult(
                    converged=True,
                    joint_angles=joint_angles,
                    position_error=position_error,
                    orientation_error=orientation_error,
                    iterations_used=iteration_index + 1,
                )

            jacobian = pin.computeFrameJacobian(
                self.model_,
                self.data_,
                joint_angles,
                self.tcp_frame_id_,
                pin.ReferenceFrame.LOCAL,
            )

            delta_joint_angles = params.step_size * jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T + identity_damping,
                error_twist,
            )
            joint_angles = joint_angles + delta_joint_angles

        pin.forwardKinematics(self.model_, self.data_, joint_angles)
        pin.updateFramePlacements(self.model_, self.data_)
        current_pose = self.data_.oMf[self.tcp_frame_id_]
        final_twist = pin.log6(current_pose.actInv(target_pose)).vector

        return IkResult(
            converged=False,
            joint_angles=joint_angles,
            position_error=float(np.linalg.norm(final_twist[:3])),
            orientation_error=float(np.linalg.norm(final_twist[3:])),
            iterations_used=params.max_iterations,
        )
