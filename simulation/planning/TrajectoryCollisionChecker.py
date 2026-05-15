"""
FK-based collision/clearance checking for multi-robot coordination.

Two levels of checking:
  Level 1 -- Point-vs-Zone: checks N body points along an interpolated
             path against a zone centre (e.g. pickup area).
  Level 2 -- Trajectory-vs-Trajectory: checks body-point swept volumes
             of two robots against each other over a time window.

Scoped monitoring avoids unnecessary checks when robots are clearly in
their own board halves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from simulation.core.CoordinateTransform import WorldToRobotBaseTransform
from simulation.planning.ForwardKinematicsProtocol import MultiPointForwardKinematics
from simulation.planning.TrajectoryStore import TrajectoryStore

logger = logging.getLogger(__name__)


@dataclass
class SharedAreaPolicy:
    """Defines when trajectory-vs-trajectory monitoring is active."""
    board_center_x_m: float = 0.0
    shared_corridor_half_width_m: float = 0.20
    monitor_when_in_other_half: bool = True

    def requiresTrajectoryMonitoring(
        self,
        tcp_world_x_m: float,
        own_half: str,
    ) -> bool:
        """Return True if the robot's TCP is in a shared area."""
        in_corridor = abs(tcp_world_x_m - self.board_center_x_m) <= self.shared_corridor_half_width_m
        if in_corridor:
            return True
        if self.monitor_when_in_other_half:
            if own_half == "left" and tcp_world_x_m > self.board_center_x_m:
                return True
            if own_half == "right" and tcp_world_x_m < self.board_center_x_m:
                return True
        return False


@dataclass
class ClearanceCheckResult:
    """Result of a collision/clearance check."""
    is_clear: bool
    minimum_distance_m: float
    closest_point_pair: Tuple[str, str] = ("", "")
    closest_time_s: float = 0.0


class TrajectoryCollisionChecker:
    """FK-based clearance checking for multi-robot workspace coordination."""

    def __init__(
        self,
        fk_solver: MultiPointForwardKinematics,
        base_transforms: Dict[str, WorldToRobotBaseTransform],
        inter_robot_clearance_m: float = 0.20,
        zone_clearance_num_samples: int = 12,
        trajectory_check_num_samples: int = 12,
        trajectory_time_margin_s: float = 2.0,
    ) -> None:
        self._fk_solver = fk_solver
        self._base_transforms = base_transforms
        self._inter_robot_clearance_m = inter_robot_clearance_m
        self._zone_clearance_num_samples = zone_clearance_num_samples
        self._trajectory_check_num_samples = trajectory_check_num_samples
        self._trajectory_time_margin_s = trajectory_time_margin_s

    def isPathClearOfZone(
        self,
        robot_name: str,
        start_angles: List[float],
        end_angles: List[float],
        zone_center_world: Tuple[float, float, float],
        clearance_radius: float,
        num_samples: int | None = None,
    ) -> ClearanceCheckResult:
        """Check all 5 body points along an interpolated path against a spherical zone."""
        actual_samples = num_samples or self._zone_clearance_num_samples
        zone_arr = np.array(zone_center_world, dtype=np.float64)
        start_arr = np.array(start_angles, dtype=np.float64)
        end_arr = np.array(end_angles, dtype=np.float64)

        minimum_distance = float("inf")
        closest_label = ""

        sample_count = max(actual_samples, 1)
        for sample_index in range(sample_count + 1):
            alpha = sample_index / sample_count
            interpolated_angles = list(start_arr + alpha * (end_arr - start_arr))
            body_points_world = self.computeBodyPointsWorld(robot_name, interpolated_angles)

            body_result = self._fk_solver.computeBodyPoints(interpolated_angles)
            labels = body_result.labels

            for point_idx, point_world in enumerate(body_points_world):
                distance = float(np.linalg.norm(np.array(point_world) - zone_arr))
                if distance < minimum_distance:
                    minimum_distance = distance
                    closest_label = labels[point_idx] if point_idx < len(labels) else ""

        is_clear = minimum_distance >= clearance_radius
        return ClearanceCheckResult(
            is_clear=is_clear,
            minimum_distance_m=minimum_distance,
            closest_point_pair=(closest_label, "zone_center"),
        )

    def isPathClearOfTrajectory(
        self,
        robot_name: str,
        start_angles: List[float],
        end_angles: List[float],
        motion_start_s: float,
        motion_end_s: float,
        other_robot_name: str,
        trajectory_store: TrajectoryStore,
        shared_area_policy: SharedAreaPolicy | None = None,
    ) -> ClearanceCheckResult:
        """Check body-point swept volumes of two robots over a time window."""
        start_arr = np.array(start_angles, dtype=np.float64)
        end_arr = np.array(end_angles, dtype=np.float64)

        time_window_start = motion_start_s - self._trajectory_time_margin_s
        time_window_end = motion_end_s + self._trajectory_time_margin_s

        minimum_distance = float("inf")
        closest_pair = ("", "")
        closest_time = 0.0

        sample_count = max(self._trajectory_check_num_samples, 1)
        motion_duration_s = max(motion_end_s - motion_start_s, 1e-9)
        labels_a = self._fk_solver.computeBodyPoints(start_angles).labels
        labels_b = self._fk_solver.computeBodyPoints(end_angles).labels

        for sample_index in range(sample_count + 1):
            alpha_window = sample_index / sample_count
            current_time = time_window_start + alpha_window * (time_window_end - time_window_start)

            if current_time <= motion_start_s:
                alpha_motion = 0.0
            elif current_time >= motion_end_s:
                alpha_motion = 1.0
            else:
                alpha_motion = (current_time - motion_start_s) / motion_duration_s

            robot_a_angles = list(start_arr + alpha_motion * (end_arr - start_arr))
            body_a_world = self.computeBodyPointsWorld(robot_name, robot_a_angles)

            if shared_area_policy is not None:
                tcp_world = body_a_world[-1]
                base_tf = self._base_transforms.get(robot_name)
                own_half = "left"
                if base_tf is not None:
                    own_half = "left" if base_tf.base_position[0] <= shared_area_policy.board_center_x_m else "right"

                if not shared_area_policy.requiresTrajectoryMonitoring(
                    tcp_world[0], own_half,
                ):
                    continue

            robot_b_angles = trajectory_store.interpolateAtTime(other_robot_name, current_time)
            if robot_b_angles is None:
                continue

            body_b_world = self.computeBodyPointsWorld(other_robot_name, robot_b_angles)

            for idx_a, point_a in enumerate(body_a_world):
                for idx_b, point_b in enumerate(body_b_world):
                    distance = float(np.linalg.norm(
                        np.array(point_a) - np.array(point_b),
                    ))
                    if distance < minimum_distance:
                        minimum_distance = distance
                        label_a = labels_a[idx_a] if idx_a < len(labels_a) else ""
                        label_b = labels_b[idx_b] if idx_b < len(labels_b) else ""
                        closest_pair = (label_a, label_b)
                        closest_time = current_time

        is_clear = minimum_distance >= self._inter_robot_clearance_m
        return ClearanceCheckResult(
            is_clear=is_clear,
            minimum_distance_m=minimum_distance,
            closest_point_pair=closest_pair,
            closest_time_s=closest_time,
        )

    def computeBodyPointsWorld(
        self,
        robot_name: str,
        joint_angles: List[float],
    ) -> List[Tuple[float, float, float]]:
        """Compute all body-point positions in world frame."""
        body_result = self._fk_solver.computeBodyPoints(joint_angles)
        base_tf = self._base_transforms.get(robot_name)
        if base_tf is None:
            return body_result.points
        return [base_tf.inverseTransformPosition(point) for point in body_result.points]
