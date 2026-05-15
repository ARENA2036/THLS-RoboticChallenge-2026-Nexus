"""
Cartesian path planner for straight-line TCP motions.

Produces evenly-spaced SE3 waypoints along a linear path (LERP for
position, SLERP for orientation) with associated timestamps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pinocchio as pin
from scipy.spatial.transform import Rotation, Slerp


@dataclass
class CartesianWaypoint:
    """A single SE3 waypoint with its timestamp."""
    timestamp_s: float
    pose: pin.SE3


@dataclass
class CartesianPathResult:
    """Output of the Cartesian path planner."""
    waypoints: List[CartesianWaypoint]
    total_distance_m: float
    total_rotation_rad: float


def _rotation_matrix_to_scipy(rotation_matrix: np.ndarray) -> Rotation:
    return Rotation.from_matrix(rotation_matrix)


def _scipy_to_rotation_matrix(rotation: Rotation) -> np.ndarray:
    return rotation.as_matrix()


def planCartesianPath(
    start_pose: pin.SE3,
    target_pose: pin.SE3,
    duration_s: float,
    num_waypoints: int = 50,
) -> CartesianPathResult:
    """
    Plan a straight-line Cartesian path between two SE3 poses.

    Position is linearly interpolated (LERP).
    Orientation is spherically interpolated (SLERP).

    Args:
        start_pose:     TCP pose at the beginning of the motion.
        target_pose:    TCP pose at the end of the motion.
        duration_s:     Total motion time in seconds.
        num_waypoints:  Number of waypoints including start and end.

    Returns:
        CartesianPathResult with the interpolated waypoints and path metrics.
    """
    if num_waypoints < 2:
        raise ValueError(f"num_waypoints must be >= 2, got {num_waypoints}")
    if duration_s <= 0.0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")

    start_position = start_pose.translation.copy()
    target_position = target_pose.translation.copy()

    total_distance_m = float(np.linalg.norm(target_position - start_position))

    rotation_start = _rotation_matrix_to_scipy(start_pose.rotation)
    rotation_target = _rotation_matrix_to_scipy(target_pose.rotation)

    relative_rotation = rotation_start.inv() * rotation_target
    total_rotation_rad = float(relative_rotation.magnitude())

    slerp_interpolator = Slerp(
        times=[0.0, 1.0],
        rotations=Rotation.concatenate([rotation_start, rotation_target]),
    )

    waypoints: List[CartesianWaypoint] = []

    for waypoint_index in range(num_waypoints):
        interpolation_ratio = waypoint_index / max(num_waypoints - 1, 1)
        timestamp_s = interpolation_ratio * duration_s

        position = start_position + interpolation_ratio * (target_position - start_position)

        rotation_matrix = _scipy_to_rotation_matrix(
            slerp_interpolator([interpolation_ratio])[0]
        )

        pose = pin.SE3(rotation_matrix, position)
        waypoints.append(CartesianWaypoint(timestamp_s=timestamp_s, pose=pose))

    return CartesianPathResult(
        waypoints=waypoints,
        total_distance_m=total_distance_m,
        total_rotation_rad=total_rotation_rad,
    )
