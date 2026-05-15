"""
Simulation hardware adapter -- implements RobotHardwareInterface for MuJoCo.

This layer validates and normalizes command/feedback contracts and delegates
execution to the backend SimulationExecutor.
"""

from typing import Dict, List

from simulation.backend.SimulationExecutor import SimulationExecutor
from simulation.interface.HardwareInterfaceModels import (
    CommandAck,
    FtsWrench,
    InterfaceErrorSeverity,
    RobotError,
    RobotFeedback,
    TickResult,
    TimedSetpoint,
)


class SimulationHardwareAdapter:
    def __init__(self, simulation_executor: SimulationExecutor, command_frequency_hz: float = 125.0) -> None:
        self.simulation_executor = simulation_executor
        self.command_frequency_hz = command_frequency_hz
        self.robot_names = set(self.simulation_executor.robot_command_states.keys())

    def sendTimedSetpoint(
        self,
        robot_name: str,
        timestamp_s: float,
        joint_angles: List[float] | None = None,
        gripper_command_value: float | None = None,
    ) -> CommandAck:
        if robot_name not in self.robot_names:
            return CommandAck(
                accepted=False,
                robot_name=robot_name,
                timestamp_s=timestamp_s,
                reason=f"Unknown robot: {robot_name}",
            )

        if joint_angles is not None and len(joint_angles) != 6:
            return CommandAck(
                accepted=False,
                robot_name=robot_name,
                timestamp_s=timestamp_s,
                reason=f"Expected 6 joint angles, received {len(joint_angles)}",
            )

        if timestamp_s < 0.0:
            return CommandAck(
                accepted=False,
                robot_name=robot_name,
                timestamp_s=timestamp_s,
                reason="timestamp_s must be >= 0.0",
            )

        timed_setpoint = TimedSetpoint(
            robot_name=robot_name,
            timestamp_s=timestamp_s,
            joint_angles=joint_angles,
            gripper_command_value=gripper_command_value,
        )
        self.simulation_executor.queue_setpoint(timed_setpoint)
        return CommandAck(
            accepted=True,
            robot_name=robot_name,
            timestamp_s=timestamp_s,
            reason=None,
        )

    def getFeedback(self, robot_name: str) -> RobotFeedback:
        if robot_name not in self.robot_names:
            raise ValueError(f"Unknown robot: {robot_name}")
        return self.simulation_executor.get_feedback(robot_name)

    def getRobotErrors(self, robot_name: str) -> List[RobotError]:
        if robot_name not in self.robot_names:
            return [
                RobotError(
                    robot_name=robot_name,
                    timestamp_s=self.simulation_executor.current_timestamp_s,
                    error_code="ROBOT_NOT_FOUND",
                    message=f"Unknown robot: {robot_name}",
                    severity=InterfaceErrorSeverity.ERROR,
                )
            ]
        return self.simulation_executor.pop_robot_errors(robot_name)

    def stepToTimestamp(self, timestamp_s: float) -> TickResult:
        if timestamp_s < self.simulation_executor.current_timestamp_s:
            error_item = RobotError(
                robot_name="global",
                timestamp_s=self.simulation_executor.current_timestamp_s,
                error_code="INVALID_TIMESTAMP",
                message=(
                    f"Requested timestamp {timestamp_s:.6f} is behind "
                    f"current timestamp {self.simulation_executor.current_timestamp_s:.6f}"
                ),
                severity=InterfaceErrorSeverity.WARNING,
            )
            return TickResult(
                success=False,
                target_timestamp_s=timestamp_s,
                current_timestamp_s=self.simulation_executor.current_timestamp_s,
                executed_ticks=0,
                errors=[error_item],
            )

        executed_ticks = self.simulation_executor.step_to_timestamp(timestamp_s)
        collected_errors: List[RobotError] = []
        for robot_name in self.robot_names:
            collected_errors.extend(self.simulation_executor.pop_robot_errors(robot_name))

        return TickResult(
            success=True,
            target_timestamp_s=timestamp_s,
            current_timestamp_s=self.simulation_executor.current_timestamp_s,
            executed_ticks=executed_ticks,
            errors=collected_errors,
        )

    def getCurrentTimestamp(self) -> float:
        return self.simulation_executor.current_timestamp_s

    def getInterfaceInfo(self) -> Dict[str, object]:
        return {
            "type": "custom_ur_inspired",
            "command_frequency_hz": self.command_frequency_hz,
            "robot_names": sorted(self.robot_names),
        }

