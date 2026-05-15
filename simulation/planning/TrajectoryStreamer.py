"""
125 Hz trajectory streaming from planning output to Layer B interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from simulation.interface.HardwareInterfaceModels import TickResult
from simulation.interface.RobotHardwareProtocol import RobotHardwareInterface
from simulation.planning.PlanningModels import PlanningResult


@dataclass
class StreamExecutionResult:
    success: bool
    streamed_points: int
    final_timestamp_s: float
    message: str


class TrajectoryStreamer:
    def __init__(self, hardware_interface: RobotHardwareInterface, stream_frequency_hz: float = 125.0) -> None:
        self.hardware_interface = hardware_interface
        self.stream_frequency_hz = stream_frequency_hz
        self.tick_period_s = 1.0 / max(stream_frequency_hz, 1.0)

    def execute_planning_result(
        self,
        planning_result: PlanningResult,
        start_timestamp_s: float | None = None,
        on_tick_callback: Optional[Callable[[], None]] = None,
    ) -> StreamExecutionResult:
        if not planning_result.success or not planning_result.trajectory:
            return StreamExecutionResult(
                success=False,
                streamed_points=0,
                final_timestamp_s=self.hardware_interface.getCurrentTimestamp(),
                message="No executable trajectory in planning result.",
            )

        if start_timestamp_s is None:
            start_timestamp_s = self.hardware_interface.getCurrentTimestamp() + self.tick_period_s

        resampled_trajectory = self._resample_to_fixed_rate(planning_result, start_timestamp_s)
        for setpoint_item in resampled_trajectory:
            ack_response = self.hardware_interface.sendTimedSetpoint(
                robot_name=planning_result.robot_name,
                timestamp_s=setpoint_item["timestamp_s"],
                joint_angles=setpoint_item["joint_angles"],
                gripper_command_value=setpoint_item["gripper_command_value"],
            )
            if not ack_response.accepted:
                return StreamExecutionResult(
                    success=False,
                    streamed_points=0,
                    final_timestamp_s=self.hardware_interface.getCurrentTimestamp(),
                    message=ack_response.reason or "Setpoint rejected.",
                )

        final_timestamp_s = resampled_trajectory[-1]["timestamp_s"]

        if on_tick_callback is not None:
            return self._step_with_callback(resampled_trajectory, final_timestamp_s, on_tick_callback)

        tick_response: TickResult = self.hardware_interface.stepToTimestamp(final_timestamp_s)
        if not tick_response.success:
            return StreamExecutionResult(
                success=False,
                streamed_points=len(resampled_trajectory),
                final_timestamp_s=tick_response.current_timestamp_s,
                message="Interface step failed during streaming execution.",
            )

        return StreamExecutionResult(
            success=True,
            streamed_points=len(resampled_trajectory),
            final_timestamp_s=tick_response.current_timestamp_s,
            message="Trajectory streamed successfully.",
        )

    def _step_with_callback(
        self,
        resampled_trajectory: List[dict],
        final_timestamp_s: float,
        on_tick_callback: Callable[[], None],
    ) -> StreamExecutionResult:
        """Step through the trajectory tick-by-tick, invoking the callback after each tick."""
        current_time_s = self.hardware_interface.getCurrentTimestamp()
        while current_time_s + 1e-12 < final_timestamp_s:
            next_time_s = min(current_time_s + self.tick_period_s, final_timestamp_s)
            tick_response: TickResult = self.hardware_interface.stepToTimestamp(next_time_s)
            if not tick_response.success:
                return StreamExecutionResult(
                    success=False,
                    streamed_points=len(resampled_trajectory),
                    final_timestamp_s=tick_response.current_timestamp_s,
                    message="Interface step failed during streaming execution.",
                )
            on_tick_callback()
            current_time_s = tick_response.current_timestamp_s

        return StreamExecutionResult(
            success=True,
            streamed_points=len(resampled_trajectory),
            final_timestamp_s=current_time_s,
            message="Trajectory streamed successfully.",
        )

    def _resample_to_fixed_rate(self, planning_result: PlanningResult, start_timestamp_s: float) -> List[dict]:
        source_trajectory = planning_result.trajectory
        if len(source_trajectory) == 1:
            only_item = source_trajectory[0]
            return [
                {
                    "timestamp_s": start_timestamp_s,
                    "joint_angles": only_item.joint_angles,
                    "gripper_command_value": only_item.gripper_command_value,
                }
            ]

        total_duration_s = max(source_trajectory[-1].timestamp_s, self.tick_period_s)
        num_samples = max(2, int(round(total_duration_s / self.tick_period_s)) + 1)
        resampled: List[dict] = []

        for sample_index in range(num_samples):
            local_time_s = min(sample_index * self.tick_period_s, total_duration_s)
            source_index = self._find_segment_index(source_trajectory, local_time_s)
            start_item = source_trajectory[source_index]
            end_item = source_trajectory[min(source_index + 1, len(source_trajectory) - 1)]
            segment_duration = max(end_item.timestamp_s - start_item.timestamp_s, 1e-9)
            segment_ratio = min(max((local_time_s - start_item.timestamp_s) / segment_duration, 0.0), 1.0)
            interpolated_joint_angles = [
                start_value + segment_ratio * (end_value - start_value)
                for start_value, end_value in zip(start_item.joint_angles, end_item.joint_angles)
            ]
            gripper_command_value = end_item.gripper_command_value
            resampled.append(
                {
                    "timestamp_s": start_timestamp_s + local_time_s,
                    "joint_angles": interpolated_joint_angles,
                    "gripper_command_value": gripper_command_value,
                }
            )

        return resampled

    @staticmethod
    def _find_segment_index(source_trajectory, local_time_s: float) -> int:
        for segment_index in range(len(source_trajectory) - 1):
            if source_trajectory[segment_index].timestamp_s <= local_time_s <= source_trajectory[segment_index + 1].timestamp_s:
                return segment_index
        return max(0, len(source_trajectory) - 2)

