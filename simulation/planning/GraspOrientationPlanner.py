"""
Grasp orientation planner for part pickup and target placement.

Computes TCP quaternions at pickup and placement that account for
Z-rotations, validates wrist delta against joint limits.

The planner is **pure compute** -- no MuJoCo or Pinocchio dependency --
so it can be unit-tested in isolation.  Object orientations come from
an ``OrientationSource`` (random, camera, or fixed for testing).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from simulation.core.RotationUtils import composeZRotation, normaliseAngleDeg
from simulation.planning.OrientationSource import (
    OrientationSource,
    RandomOrientationSource,
)


@dataclass
class GraspPlan:
    """Result of grasp orientation planning for a single object."""
    pickup_orientation_deg: float
    placement_orientation_deg: float
    wrist_delta_deg: float
    pickup_grasp_quat_wxyz: Tuple[float, float, float, float]
    placement_grasp_quat_wxyz: Tuple[float, float, float, float]
    is_feasible: bool


class GraspOrientationPlanner:
    """Plans TCP orientations for pickup and target placement.

    The planner works exclusively with **Z-axis rotations** applied to a
    base grasp quaternion (the gripper pointing straight down).  Wrist
    compensation (J6) absorbs the full orientation delta.
    """

    def __init__(
        self,
        orientation_source: Optional[OrientationSource] = None,
        seed: int = 42,
        wrist_joint_limits_rad: Tuple[float, float] = (-6.283, 6.283),
    ) -> None:
        self._orientation_source = orientation_source or RandomOrientationSource(seed)
        self._wrist_limits_rad = wrist_joint_limits_rad

    def generatePickupOrientation(self, object_id: str) -> float:
        """Return a Z-rotation in degrees for *object_id* from the orientation source."""
        return self._orientation_source.getObjectOrientation(object_id)

    def computeGraspPlan(
        self,
        base_grasp_quat_wxyz: Tuple[float, float, float, float],
        pickup_orientation_deg: float,
        placement_orientation_deg: float,
    ) -> GraspPlan:
        """Compute pickup/placement TCP quaternions and validate wrist delta."""
        pickup_quat = composeZRotation(base_grasp_quat_wxyz, pickup_orientation_deg)
        placement_quat = composeZRotation(base_grasp_quat_wxyz, placement_orientation_deg)

        delta_deg = normaliseAngleDeg(placement_orientation_deg - pickup_orientation_deg)
        delta_rad = math.radians(delta_deg)

        is_feasible = (
            self._wrist_limits_rad[0] <= delta_rad <= self._wrist_limits_rad[1]
        )

        return GraspPlan(
            pickup_orientation_deg=pickup_orientation_deg,
            placement_orientation_deg=placement_orientation_deg,
            wrist_delta_deg=delta_deg,
            pickup_grasp_quat_wxyz=pickup_quat,
            placement_grasp_quat_wxyz=placement_quat,
            is_feasible=is_feasible,
        )


