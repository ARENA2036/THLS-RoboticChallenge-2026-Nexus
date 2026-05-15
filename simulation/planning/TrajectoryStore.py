"""
Per-robot queued trajectory storage for inter-robot collision checking.

Both the WorkspaceCoordinator (to add segments) and the
TrajectoryCollisionChecker (to query the other robot's state at a
given time) use ``interpolateAtTime()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class QueuedMotionSegment:
    """A single motion segment with linear joint-angle interpolation."""
    robot_name: str
    start_time_s: float
    end_time_s: float
    start_angles: List[float]
    end_angles: List[float]


class TrajectoryStore:
    """Stores queued motion segments per robot and provides time-based interpolation."""

    def __init__(self) -> None:
        self._segments: Dict[str, List[QueuedMotionSegment]] = {}

    def addSegment(self, segment: QueuedMotionSegment) -> None:
        robot_segments = self._segments.setdefault(segment.robot_name, [])
        robot_segments.append(segment)
        robot_segments.sort(
            key=lambda queued_segment: (
                queued_segment.start_time_s,
                queued_segment.end_time_s,
            ),
        )

    def getSegmentsInWindow(
        self,
        robot_name: str,
        time_start_s: float,
        time_end_s: float,
    ) -> List[QueuedMotionSegment]:
        """Return all segments for *robot_name* overlapping [time_start_s, time_end_s]."""
        result: List[QueuedMotionSegment] = []
        for segment in self._segments.get(robot_name, []):
            if segment.end_time_s >= time_start_s and segment.start_time_s <= time_end_s:
                result.append(segment)
        return result

    def interpolateAtTime(
        self,
        robot_name: str,
        time_s: float,
    ) -> Optional[List[float]]:
        """Linearly interpolate joint angles at *time_s* from stored segments.

        Returns ``None`` if no segment covers the requested time.
        """
        for segment in self._segments.get(robot_name, []):
            if segment.start_time_s <= time_s <= segment.end_time_s:
                duration = segment.end_time_s - segment.start_time_s
                if duration < 1e-12:
                    return list(segment.end_angles)
                alpha = (time_s - segment.start_time_s) / duration
                return [
                    start_val + alpha * (end_val - start_val)
                    for start_val, end_val in zip(segment.start_angles, segment.end_angles)
                ]
        return None

    def getLatestEndTime(self, robot_name: str) -> float:
        """Return the latest end_time_s across all segments for robot_name."""
        segments = self._segments.get(robot_name, [])
        if not segments:
            return 0.0
        return max(segment.end_time_s for segment in segments)
