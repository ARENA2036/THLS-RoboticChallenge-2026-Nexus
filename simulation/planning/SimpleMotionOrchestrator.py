"""
Minimal orchestrator facade for MOVEJ and MOVEL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, TYPE_CHECKING

from simulation.interface.RobotHardwareProtocol import RobotHardwareInterface
from simulation.planning.MoveItPlannerClient import PlannerClient
from simulation.planning.PlanningModels import MoveJRequest, MoveLRequest, PlanningError
from simulation.planning.TrajectoryStreamer import StreamExecutionResult, TrajectoryStreamer

if TYPE_CHECKING:
    from simulation.visualization.PathRecorder import PathRecorder


@dataclass
class MotionExecutionResult:
    success: bool
    fallback_used: bool
    message: str
    stream_result: StreamExecutionResult | None = None
    planning_error: PlanningError | None = None


class SimpleMotionOrchestrator:
    def __init__(
        self,
        hardware_interface: RobotHardwareInterface,
        planner_client: PlannerClient,
        trajectory_streamer: TrajectoryStreamer | None = None,
        path_recorder: Optional["PathRecorder"] = None,
    ) -> None:
        self.hardware_interface = hardware_interface
        self.planner_client = planner_client
        self.trajectory_streamer = trajectory_streamer or TrajectoryStreamer(hardware_interface=hardware_interface)
        self.path_recorder = path_recorder

    def executeMoveJ(
        self,
        request_data: MoveJRequest,
        record_segment: Optional[str] = None,
        record_color_rgba: Tuple[float, float, float, float] = (0.0, 0.8, 0.2, 1.0),
        record_tube_radius_m: float = 0.003,
    ) -> MotionExecutionResult:
        if request_data.start_joint_angles is None:
            feedback_data = self.hardware_interface.getFeedback(request_data.robot_name)
            request_data = request_data.model_copy(update={"start_joint_angles": feedback_data.joint_angles})

        planning_result = self.planner_client.plan_movej(request_data)
        if not planning_result.success:
            return MotionExecutionResult(
                success=False,
                fallback_used=False,
                message="MOVEJ planning failed.",
                planning_error=planning_result.planning_error,
            )

        is_recording = record_segment is not None and self.path_recorder is not None
        if is_recording:
            self.path_recorder.startRecording(
                robot_name=request_data.robot_name,
                segment_name=record_segment,
                color_rgba=record_color_rgba,
                tube_radius_m=record_tube_radius_m,
            )

        tick_callback = self.path_recorder.sampleCurrentPositions if is_recording else None
        stream_result = self.trajectory_streamer.execute_planning_result(
            planning_result, on_tick_callback=tick_callback,
        )

        if is_recording:
            self.path_recorder.sampleCurrentPositions()
            self.path_recorder.stopRecording(record_segment)

        return MotionExecutionResult(
            success=stream_result.success,
            fallback_used=planning_result.fallback_used,
            message=stream_result.message,
            stream_result=stream_result,
            planning_error=planning_result.planning_error,
        )

    def executeMoveL(
        self,
        request_data: MoveLRequest,
        record_segment: Optional[str] = None,
        record_color_rgba: Tuple[float, float, float, float] = (0.0, 0.8, 0.2, 1.0),
        record_tube_radius_m: float = 0.003,
    ) -> MotionExecutionResult:
        if request_data.start_joint_angles is None:
            feedback_data = self.hardware_interface.getFeedback(request_data.robot_name)
            request_data = request_data.model_copy(update={"start_joint_angles": feedback_data.joint_angles})

        planning_result = self.planner_client.plan_movel(request_data)
        if not planning_result.success:
            return MotionExecutionResult(
                success=False,
                fallback_used=False,
                message="MOVEL planning failed.",
                planning_error=planning_result.planning_error,
            )

        is_recording = record_segment is not None and self.path_recorder is not None
        if is_recording:
            self.path_recorder.startRecording(
                robot_name=request_data.robot_name,
                segment_name=record_segment,
                color_rgba=record_color_rgba,
                tube_radius_m=record_tube_radius_m,
            )

        tick_callback = self.path_recorder.sampleCurrentPositions if is_recording else None
        stream_result = self.trajectory_streamer.execute_planning_result(
            planning_result, on_tick_callback=tick_callback,
        )

        if is_recording:
            self.path_recorder.sampleCurrentPositions()
            self.path_recorder.stopRecording(record_segment)

        return MotionExecutionResult(
            success=stream_result.success,
            fallback_used=False,
            message=stream_result.message,
            stream_result=stream_result,
            planning_error=planning_result.planning_error,
        )

