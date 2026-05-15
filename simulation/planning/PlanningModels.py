"""
Minimal planning models for Step C.
"""

from enum import StrEnum
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field


class MotionType(StrEnum):
    MOVEJ = "MOVEJ"
    MOVEL = "MOVEL"


class PoseTarget(BaseModel):
    position_m: Tuple[float, float, float]
    quat_wxyz: Tuple[float, float, float, float]


class MoveJRequest(BaseModel):
    robot_name: str
    target_joint_angles: List[float] = Field(min_length=6, max_length=6)
    start_joint_angles: Optional[List[float]] = Field(default=None, min_length=6, max_length=6)
    duration_s: float = Field(default=2.0, gt=0.0)


class MoveLRequest(BaseModel):
    robot_name: str
    target_pose: PoseTarget
    start_joint_angles: Optional[List[float]] = Field(default=None, min_length=6, max_length=6)
    duration_s: float = Field(default=2.0, gt=0.0)


class TimedJointPoint(BaseModel):
    timestamp_s: float = Field(ge=0.0)
    joint_angles: List[float] = Field(min_length=6, max_length=6)
    gripper_command_value: Optional[float] = None


class PlanningError(BaseModel):
    code: str
    message: str


class PlanningResult(BaseModel):
    motion_type: MotionType
    robot_name: str
    success: bool
    trajectory: List[TimedJointPoint] = Field(default_factory=list)
    fallback_used: bool = False
    planning_error: Optional[PlanningError] = None

