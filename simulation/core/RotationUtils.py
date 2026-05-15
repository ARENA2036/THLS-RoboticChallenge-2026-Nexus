"""
Consolidated rotation and quaternion utilities.

All rotation/quaternion operations in the simulation package import from
this single module, eliminating duplication across CoordinateTransform,
SimulationExecutor, GraspOrientationPlanner, SceneObjectOverlay, and
run_board_setup.

Convention: quaternions are scalar-first (w, x, y, z) throughout.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np


def quatWxyzToRotationMatrix(
    w: float, x: float, y: float, z: float,
) -> np.ndarray:
    """Convert a scalar-first quaternion to a 3x3 rotation matrix."""
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)],
    ], dtype=np.float64)


def rotationMatrixToQuatWxyz(
    rotation_matrix: np.ndarray,
) -> Tuple[float, float, float, float]:
    """Convert a 3x3 rotation matrix to a scalar-first quaternion (Shepperd method)."""
    trace = np.trace(rotation_matrix)
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (rotation_matrix[2, 1] - rotation_matrix[1, 2]) * s
        y = (rotation_matrix[0, 2] - rotation_matrix[2, 0]) * s
        z = (rotation_matrix[1, 0] - rotation_matrix[0, 1]) * s
    elif rotation_matrix[0, 0] > rotation_matrix[1, 1] and rotation_matrix[0, 0] > rotation_matrix[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rotation_matrix[0, 0] - rotation_matrix[1, 1] - rotation_matrix[2, 2])
        w = (rotation_matrix[2, 1] - rotation_matrix[1, 2]) / s
        x = 0.25 * s
        y = (rotation_matrix[0, 1] + rotation_matrix[1, 0]) / s
        z = (rotation_matrix[0, 2] + rotation_matrix[2, 0]) / s
    elif rotation_matrix[1, 1] > rotation_matrix[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rotation_matrix[1, 1] - rotation_matrix[0, 0] - rotation_matrix[2, 2])
        w = (rotation_matrix[0, 2] - rotation_matrix[2, 0]) / s
        x = (rotation_matrix[0, 1] + rotation_matrix[1, 0]) / s
        y = 0.25 * s
        z = (rotation_matrix[1, 2] + rotation_matrix[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + rotation_matrix[2, 2] - rotation_matrix[0, 0] - rotation_matrix[1, 1])
        w = (rotation_matrix[1, 0] - rotation_matrix[0, 1]) / s
        x = (rotation_matrix[0, 2] + rotation_matrix[2, 0]) / s
        y = (rotation_matrix[1, 2] + rotation_matrix[2, 1]) / s
        z = 0.25 * s
    return (float(w), float(x), float(y), float(z))


def composeZRotation(
    base_quat_wxyz: Tuple[float, float, float, float],
    angle_deg: float,
) -> Tuple[float, float, float, float]:
    """Return ``Rz(angle_deg) * base_quat`` as (w, x, y, z).

    Rz is a rotation around the **world Z-axis**.  Pre-multiplying by Rz
    rotates the gripper in the world frame.
    """
    half_rad = math.radians(angle_deg) / 2.0
    rz_w = math.cos(half_rad)
    rz_z = math.sin(half_rad)

    bw, bx, by, bz = base_quat_wxyz

    result_w = rz_w * bw - rz_z * bz
    result_x = rz_w * bx - rz_z * by
    result_y = rz_w * by + rz_z * bx
    result_z = rz_w * bz + rz_z * bw

    return (result_w, result_x, result_y, result_z)


def normaliseAngleDeg(angle_deg: float) -> float:
    """Normalise an angle to the range (-180, 180]."""
    result = angle_deg % 360.0
    if result > 180.0:
        result -= 360.0
    return result


def zRotationMatrixFlat(angle_deg: float) -> np.ndarray:
    """Return a flattened 3x3 Z-rotation matrix (row-major, 9 elements)."""
    rad = math.radians(angle_deg)
    cos_val = math.cos(rad)
    sin_val = math.sin(rad)
    return np.array([
        cos_val, -sin_val, 0.0,
        sin_val,  cos_val, 0.0,
        0.0,      0.0,     1.0,
    ], dtype=np.float64)


def rotateOffsetAroundZ(offset: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate a 3D offset vector around the Z-axis by *angle_deg*."""
    rad = math.radians(angle_deg)
    cos_val = math.cos(rad)
    sin_val = math.sin(rad)
    rotated_x = cos_val * offset[0] - sin_val * offset[1]
    rotated_y = sin_val * offset[0] + cos_val * offset[1]
    return np.array([rotated_x, rotated_y, offset[2]], dtype=np.float64)


def extractYawFromRotationMatrix(xmat_flat) -> float:
    """Extract the Z-rotation (yaw) in degrees from a 3x3 row-major flat rotation matrix."""
    r00 = xmat_flat[0]
    r10 = xmat_flat[3]
    return math.degrees(math.atan2(r10, r00))
