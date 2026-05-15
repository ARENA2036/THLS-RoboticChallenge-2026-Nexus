"""
Workspace coordination for multi-robot scheduling.

Manages mutual-exclusion constraints when two robots share workspace
zones.  Designed to be re-used across assembly phases (board setup,
wire routing, etc.).

Constraints enforced:
  1. **Pickup zone**: only one robot at a time.
  2. **Board halves**: a robot may enter the other robot's half only
     when the other robot is at its home position.
  3. **Trajectory store** (optional): when provided, stores queued
     motion segments for inter-robot collision checking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

from simulation.planning.SafetyPolicy import SafetyPolicy
from simulation.planning.TrajectoryStore import QueuedMotionSegment, TrajectoryStore

logger = logging.getLogger(__name__)


@runtime_checkable
class WorkspaceZone(Protocol):
    """Protocol for workspace zone constraints."""

    def canEnter(self, robot_name: str, current_time_s: float) -> float:
        """Return earliest time robot_name can enter this zone."""
        ...

    def notifyEntered(self, robot_name: str, time_s: float) -> None: ...

    def notifyExited(self, robot_name: str, time_s: float) -> None: ...


@dataclass
class RobotScheduleState:
    """Mutable scheduling state for a single robot."""
    current_time_s: float = 0.0
    at_home_since_s: float = 0.0
    own_board_half: str = "left"


class WorkspaceCoordinator:
    """Coordinates scheduling constraints between two robots.

    All methods are pure-compute (no MuJoCo calls).  They return the
    *earliest allowed start time* considering the relevant constraint.
    The caller is responsible for actually queuing motions at those
    times and calling the ``release*`` / ``notify*`` methods afterward.
    """

    def __init__(
        self,
        robot_names: List[str],
        robot_base_positions: Dict[str, Tuple[float, float, float]],
        board_center_x: float = 0.0,
        pickup_clearance_radius_m: float = 0.45,
        safety_policy: SafetyPolicy = SafetyPolicy.STRICT_WAIT,
        max_wait_time_s: float = 120.0,
        max_retry_count: int = 200,
        trajectory_store: Optional[TrajectoryStore] = None,
        home_joint_angles: Optional[List[float]] = None,
    ) -> None:
        self._board_center_x = board_center_x
        self._pickup_clearance_radius_m = pickup_clearance_radius_m
        self._safety_policy = safety_policy
        self._max_wait_time_s = max_wait_time_s
        self._max_retry_count = max_retry_count
        self._trajectory_store = trajectory_store
        self._home_joint_angles = list(home_joint_angles or [0.0, -1.57, 1.57, -1.57, -1.57, 0.0])

        self._robot_states: Dict[str, RobotScheduleState] = {}
        self._pickup_zone_free_at: float = 0.0
        self._zones: List[WorkspaceZone] = []

        for robot_name in robot_names:
            base_x = robot_base_positions[robot_name][0]
            own_half = "left" if base_x <= self._board_center_x else "right"
            self._robot_states[robot_name] = RobotScheduleState(
                own_board_half=own_half,
            )

    @property
    def trajectory_store(self) -> Optional[TrajectoryStore]:
        return self._trajectory_store

    @property
    def safety_policy(self) -> SafetyPolicy:
        return self._safety_policy

    @property
    def pickup_clearance_radius_m(self) -> float:
        return self._pickup_clearance_radius_m

    @property
    def max_wait_time_s(self) -> float:
        return self._max_wait_time_s

    @property
    def max_retry_count(self) -> int:
        return self._max_retry_count

    @property
    def home_joint_angles(self) -> List[float]:
        return list(self._home_joint_angles)

    def addZone(self, zone: WorkspaceZone) -> None:
        """Register an additional workspace zone constraint."""
        self._zones.append(zone)

    def getRobotState(self, robot_name: str) -> RobotScheduleState:
        return self._robot_states[robot_name]

    def acquirePickupZone(self, robot_name: str) -> float:
        """Return the earliest time this robot can enter the pickup zone."""
        robot_state = self._robot_states[robot_name]
        earliest_start = max(robot_state.current_time_s, self._pickup_zone_free_at)
        for zone in self._zones:
            earliest_start = max(
                earliest_start,
                zone.canEnter(robot_name, earliest_start),
            )
        return earliest_start

    def releasePickupZone(self, robot_name: str, release_time_s: float) -> None:
        """Mark the pickup zone as free after the given time."""
        self._pickup_zone_free_at = release_time_s

    def acquireBoardHalf(
        self,
        robot_name: str,
        placement_world_x: float,
    ) -> float:
        """Return the earliest time this robot can reach the placement position."""
        robot_state = self._robot_states[robot_name]
        target_half = "left" if placement_world_x <= self._board_center_x else "right"

        if target_half == robot_state.own_board_half:
            earliest_start = robot_state.current_time_s
            for zone in self._zones:
                earliest_start = max(
                    earliest_start,
                    zone.canEnter(robot_name, earliest_start),
                )
            return earliest_start

        other_name = self._getOtherRobot(robot_name)
        other_state = self._robot_states[other_name]
        earliest_start = max(robot_state.current_time_s, other_state.at_home_since_s)

        if earliest_start > robot_state.current_time_s:
            logger.info(
                "    %s waits %.1fs for %s to be home before entering %s half",
                robot_name,
                earliest_start - robot_state.current_time_s,
                other_name,
                target_half,
            )

        for zone in self._zones:
            earliest_start = max(
                earliest_start,
                zone.canEnter(robot_name, earliest_start),
            )

        return earliest_start

    def registerMotionSegment(
        self,
        robot_name: str,
        start_time_s: float,
        end_time_s: float,
        start_angles: List[float],
        end_angles: List[float],
    ) -> None:
        """Store a queued motion segment in the trajectory store."""
        if self._trajectory_store is None:
            return
        self._trajectory_store.addSegment(QueuedMotionSegment(
            robot_name=robot_name,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            start_angles=start_angles,
            end_angles=end_angles,
        ))

    def notifyAtHome(self, robot_name: str, time_s: float) -> None:
        """Record that a robot has reached its home position."""
        state = self._robot_states[robot_name]
        state.at_home_since_s = time_s
        state.current_time_s = time_s

    def updateRobotTime(self, robot_name: str, time_s: float) -> None:
        state = self._robot_states[robot_name]
        state.current_time_s = time_s

    def selectNextRobot(self, pending_plans: Dict[str, List]) -> str | None:
        """Return the robot name that can proceed earliest, or None."""
        best_robot: str | None = None
        best_time = float("inf")

        for robot_name, plans in pending_plans.items():
            if not plans:
                continue
            state = self._robot_states[robot_name]
            if state.current_time_s < best_time:
                best_time = state.current_time_s
                best_robot = robot_name

        return best_robot

    def notifyZoneEntered(self, robot_name: str, time_s: float) -> None:
        for zone in self._zones:
            zone.notifyEntered(robot_name, time_s)

    def notifyZoneExited(self, robot_name: str, time_s: float) -> None:
        for zone in self._zones:
            zone.notifyExited(robot_name, time_s)

    def getOtherRobotName(self, robot_name: str) -> str:
        return self._getOtherRobot(robot_name)

    def _getOtherRobot(self, robot_name: str) -> str:
        for name in self._robot_states:
            if name != robot_name:
                return name
        return robot_name
