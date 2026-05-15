"""
Hardware abstraction protocol for robot command and feedback.

All planning and execution code should type-hint against this protocol
rather than the concrete SimulationHardwareAdapter.  A future
RealRobotAdapter (e.g. RTDE or ROS2) would implement the same
interface, making the entire planning/execution stack portable.
"""

from __future__ import annotations

from typing import List, Protocol, Set, runtime_checkable

from simulation.interface.HardwareInterfaceModels import (
    CommandAck,
    RobotFeedback,
    TickResult,
)


@runtime_checkable
class RobotHardwareInterface(Protocol):
    """Protocol boundary between planning/execution and the robot backend."""

    @property
    def robot_names(self) -> Set[str]: ...

    def sendTimedSetpoint(
        self,
        robot_name: str,
        timestamp_s: float,
        joint_angles: List[float] | None = None,
        gripper_command_value: float | None = None,
    ) -> CommandAck: ...

    def getFeedback(self, robot_name: str) -> RobotFeedback: ...

    def stepToTimestamp(self, timestamp_s: float) -> TickResult: ...

    def getCurrentTimestamp(self) -> float: ...
