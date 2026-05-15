"""
Data models for path visualization and scene overlay objects.
"""

from dataclasses import dataclass
from typing import List, Tuple

from pydantic import BaseModel, Field


class PathSegment(BaseModel):
    robot_name: str
    segment_name: str
    color_rgba: Tuple[float, float, float, float] = (0.0, 0.8, 0.2, 1.0)
    tube_radius_m: float = Field(default=0.003, gt=0.0)
    points: List[Tuple[float, float, float]] = Field(default_factory=list)
    is_recording: bool = False
    is_visible: bool = True


class PathSegmentExport(BaseModel):
    """Serialisation-friendly view of a PathSegment (no runtime flags)."""
    robot_name: str
    segment_name: str
    color_rgba: Tuple[float, float, float, float]
    tube_radius_m: float
    points: List[Tuple[float, float, float]]


@dataclass
class RecordingWindow:
    """Timestamp-bounded recording trigger for a named cable path segment."""
    segment_name: str
    robot_name: str
    start_time_s: float
    end_time_s: float
    color_rgba: Tuple[float, float, float, float]
