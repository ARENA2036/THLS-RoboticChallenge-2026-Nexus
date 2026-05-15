"""
TCP path recorder with named, independently toggleable segments.

Records the TCP position of one or more robots over time, grouping
consecutive samples into named segments that can be shown/hidden and
exported to JSON.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from simulation.backend.SimulationExecutor import SimulationExecutor
from simulation.visualization.VisualizationModels import PathSegment, PathSegmentExport

DEFAULT_COLOR_RGBA: Tuple[float, float, float, float] = (0.0, 0.8, 0.2, 1.0)
DEFAULT_TUBE_RADIUS_M: float = 0.003


class PathRecorder:
    def __init__(self, simulation_executor: SimulationExecutor) -> None:
        self.simulation_executor = simulation_executor
        self.segments: Dict[str, PathSegment] = {}
        self._segment_order: List[str] = []

    def startRecording(
        self,
        robot_name: str,
        segment_name: str,
        color_rgba: Tuple[float, float, float, float] = DEFAULT_COLOR_RGBA,
        tube_radius_m: float = DEFAULT_TUBE_RADIUS_M,
    ) -> None:
        if segment_name in self.segments and self.segments[segment_name].is_recording:
            raise ValueError(f"Segment '{segment_name}' is already being recorded.")

        segment = PathSegment(
            robot_name=robot_name,
            segment_name=segment_name,
            color_rgba=color_rgba,
            tube_radius_m=tube_radius_m,
            is_recording=True,
            is_visible=True,
        )
        self.segments[segment_name] = segment
        if segment_name not in self._segment_order:
            self._segment_order.append(segment_name)

    def stopRecording(self, segment_name: str) -> None:
        if segment_name not in self.segments:
            raise KeyError(f"Segment '{segment_name}' does not exist.")
        self.segments[segment_name].is_recording = False

    def stopAllRecordings(self) -> None:
        for segment in self.segments.values():
            segment.is_recording = False

    def sampleCurrentPositions(self) -> None:
        """Append the current TCP position to every actively recording segment."""
        sampled_positions: Dict[str, Optional[List[float]]] = {}
        for segment in self.segments.values():
            if not segment.is_recording:
                continue
            robot_name = segment.robot_name
            if robot_name not in sampled_positions:
                feedback_data = self.simulation_executor.get_feedback(robot_name)
                sampled_positions[robot_name] = feedback_data["tcp_position_m"]
            position = sampled_positions[robot_name]
            if position is not None:
                segment.points.append((position[0], position[1], position[2]))

    def setSegmentVisible(self, segment_name: str, is_visible: bool) -> None:
        if segment_name not in self.segments:
            raise KeyError(f"Segment '{segment_name}' does not exist.")
        self.segments[segment_name].is_visible = is_visible

    def setAllSegmentsVisible(self, is_visible: bool) -> None:
        for segment in self.segments.values():
            segment.is_visible = is_visible

    def getVisibleSegments(self) -> List[PathSegment]:
        return [
            self.segments[name]
            for name in self._segment_order
            if name in self.segments and self.segments[name].is_visible
        ]

    def getSegments(self) -> List[PathSegment]:
        return [self.segments[name] for name in self._segment_order if name in self.segments]

    def exportToJson(self, file_path: str) -> None:
        export_list = [
            PathSegmentExport(
                robot_name=segment.robot_name,
                segment_name=segment.segment_name,
                color_rgba=segment.color_rgba,
                tube_radius_m=segment.tube_radius_m,
                points=list(segment.points),
            )
            for segment in self.getSegments()
        ]
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file_handle:
            json.dump(
                [item.model_dump() for item in export_list],
                file_handle,
                indent=2,
            )
