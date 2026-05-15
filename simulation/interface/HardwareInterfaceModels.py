"""
Data models for UR-inspired hardware interface.
"""

from enum import StrEnum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class InterfaceErrorSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class RobotError(BaseModel):
    robot_name: str
    timestamp_s: float
    error_code: str
    message: str
    severity: InterfaceErrorSeverity
    context: Dict[str, str] = Field(default_factory=dict)


class TimedSetpoint(BaseModel):
    robot_name: str
    timestamp_s: float = Field(ge=0.0)
    joint_angles: Optional[List[float]] = None
    gripper_command_value: Optional[float] = None


class CommandAck(BaseModel):
    accepted: bool
    robot_name: str
    timestamp_s: float
    reason: Optional[str] = None


class FtsWrench(BaseModel):
    force_xyz_n: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    torque_xyz_nm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class RobotFeedback(BaseModel):
    robot_name: str
    timestamp_s: float
    joint_angles: List[float]
    tcp_position_m: List[float]
    tcp_quat_wxyz: List[float]
    gripper_command_value: float
    fts_wrench: FtsWrench


class TickResult(BaseModel):
    success: bool
    target_timestamp_s: float
    current_timestamp_s: float
    executed_ticks: int
    errors: List[RobotError] = Field(default_factory=list)

