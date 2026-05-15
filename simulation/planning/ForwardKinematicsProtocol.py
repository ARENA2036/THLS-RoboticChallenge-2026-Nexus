"""
Forward kinematics protocol for multi-point body collision checking.

Provides positions for representative points along the robot kinematic
chain, enabling body-vs-body distance checks beyond TCP-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Tuple, runtime_checkable


@dataclass
class RobotBodyPoints:
    """Positions of N representative points on the robot body, in robot-base frame."""
    points: List[Tuple[float, float, float]]
    labels: List[str]


@runtime_checkable
class MultiPointForwardKinematics(Protocol):
    """Protocol for computing FK at multiple body points."""

    def computeTcpPosition(
        self, joint_angles: List[float],
    ) -> Tuple[float, float, float]: ...

    def computeBodyPoints(
        self, joint_angles: List[float],
    ) -> RobotBodyPoints:
        """Return positions for 5 representative points along the kinematic chain."""
        ...
