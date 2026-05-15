"""
Board-to-world coordinate transform for layout generator output.

Converts 2D positions in mm (board-local) to 3D positions in meters
(MuJoCo world frame), using the board position from station config
and a configurable axis mapping.

The layout generator produces its own virtual board with computed
dimensions.  The center of that virtual board is mapped to the center
of the physical board in the scene.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from simulation.core.RotationUtils import quatWxyzToRotationMatrix, rotationMatrixToQuatWxyz
from simulation.planning.PlanningModels import PoseTarget


@dataclass
class AxisMapping:
    """Configurable mapping from layout 2D axes to world XY axes.

    layout_x_to_world: which world axis does layout +X map to ("x", "-x", "y", "-y")
    layout_y_to_world: which world axis does layout +Y map to ("x", "-x", "y", "-y")
    """
    layout_x_to_world: str = "x"
    layout_y_to_world: str = "y"

    def apply(self, layout_x_m: float, layout_y_m: float) -> Tuple[float, float]:
        world_x = 0.0
        world_y = 0.0
        for source_value, target_axis in [
            (layout_x_m, self.layout_x_to_world),
            (layout_y_m, self.layout_y_to_world),
        ]:
            if target_axis == "x":
                world_x += source_value
            elif target_axis == "-x":
                world_x -= source_value
            elif target_axis == "y":
                world_y += source_value
            elif target_axis == "-y":
                world_y -= source_value
            else:
                raise ValueError(f"Invalid axis mapping target: {target_axis}")
        return world_x, world_y

    def transformOrientationDeg(self, layout_orientation_deg: float) -> float:
        """Transform a 2D orientation angle from layout space to world space.

        The layout orientation is measured from layout +X toward layout +Y.
        This method computes the equivalent angle in the world XY plane
        (measured from world +X toward world +Y) after applying the axis
        mapping.
        """
        rad = math.radians(layout_orientation_deg)
        layout_dx = math.cos(rad)
        layout_dy = math.sin(rad)
        world_dx, world_dy = self.apply(layout_dx, layout_dy)
        return math.degrees(math.atan2(world_dy, world_dx))


class BoardToWorldTransform:
    """Transforms 2D board positions (mm) to 3D world positions (meters).

    The layout generator produces positions in mm on a virtual board
    whose dimensions are computed from the harness geometry.  The center
    of that virtual board is mapped to the center of the physical board
    in the MuJoCo scene.
    """

    def __init__(
        self,
        board_position_m: Tuple[float, float, float],
        board_thickness_m: float,
        layout_board_width_mm: float,
        layout_board_height_mm: float,
        board_center_offset_mm: Tuple[float, float] = (0.0, 0.0),
        axis_mapping: AxisMapping | None = None,
    ) -> None:
        self.board_origin_x_m = board_position_m[0]
        self.board_origin_y_m = board_position_m[1]
        self.board_surface_z_m = board_position_m[2] + board_thickness_m / 2.0

        self.layout_center_mm = (
            layout_board_width_mm / 2.0 + board_center_offset_mm[0],
            layout_board_height_mm / 2.0 + board_center_offset_mm[1],
        )

        self.axis_mapping = axis_mapping or AxisMapping()

        self.board_normal = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    @classmethod
    def fromConfigs(
        cls,
        station_config,
        layout_board_width_mm: float,
        layout_board_height_mm: float,
        board_center_offset_mm: Tuple[float, float] = (0.0, 0.0),
        axis_mapping: AxisMapping | None = None,
    ) -> "BoardToWorldTransform":
        board_cfg = station_config.board
        return cls(
            board_position_m=tuple(board_cfg.position_m),
            board_thickness_m=board_cfg.thickness_m,
            layout_board_width_mm=layout_board_width_mm,
            layout_board_height_mm=layout_board_height_mm,
            board_center_offset_mm=board_center_offset_mm,
            axis_mapping=axis_mapping,
        )

    def transformToWorld(
        self,
        layout_x_mm: float,
        layout_y_mm: float,
        height_offset_m: float = 0.0,
    ) -> Tuple[float, float, float]:
        relative_x_m = (layout_x_mm - self.layout_center_mm[0]) / 1000.0
        relative_y_m = (layout_y_mm - self.layout_center_mm[1]) / 1000.0

        mapped_x, mapped_y = self.axis_mapping.apply(relative_x_m, relative_y_m)

        world_x = self.board_origin_x_m + mapped_x
        world_y = self.board_origin_y_m + mapped_y
        world_z = self.board_surface_z_m + height_offset_m

        return (world_x, world_y, world_z)

    def computeApproachPose(
        self,
        placement_position_m: Tuple[float, float, float],
        placement_quat_wxyz: Tuple[float, float, float, float],
        approach_offset_m: float,
    ) -> PoseTarget:
        approach_position = (
            placement_position_m[0] + self.board_normal[0] * approach_offset_m,
            placement_position_m[1] + self.board_normal[1] * approach_offset_m,
            placement_position_m[2] + self.board_normal[2] * approach_offset_m,
        )
        return PoseTarget(
            position_m=approach_position,
            quat_wxyz=placement_quat_wxyz,
        )

    def computeRetreatPose(
        self,
        placement_position_m: Tuple[float, float, float],
        placement_quat_wxyz: Tuple[float, float, float, float],
        retreat_offset_m: float,
    ) -> PoseTarget:
        return self.computeApproachPose(
            placement_position_m, placement_quat_wxyz, retreat_offset_m
        )

    def getBoardNormal(self) -> np.ndarray:
        return self.board_normal.copy()

    def getBoardSurfaceZ(self) -> float:
        return self.board_surface_z_m


class WorldToRobotBaseTransform:
    """Transforms world-frame positions/orientations to a robot's base frame.

    Required because the Pinocchio IK solver works in the robot base frame,
    while the layout pipeline computes positions in the world frame.
    """

    def __init__(
        self,
        base_position_m: Tuple[float, float, float],
        base_quat_wxyz: Tuple[float, float, float, float],
    ) -> None:
        self.base_position = np.array(base_position_m, dtype=np.float64)

        w, x, y, z = base_quat_wxyz
        self.rotation_matrix = quatWxyzToRotationMatrix(w, x, y, z)
        self.rotation_matrix_inv = self.rotation_matrix.T

    def transformPosition(
        self,
        world_position_m: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        world_pos = np.array(world_position_m, dtype=np.float64)
        relative_pos = world_pos - self.base_position
        robot_pos = self.rotation_matrix_inv @ relative_pos
        return (float(robot_pos[0]), float(robot_pos[1]), float(robot_pos[2]))

    def inverseTransformPosition(
        self,
        robot_base_position_m: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        """Convert a position from robot-base frame back to world frame."""
        robot_pos = np.array(robot_base_position_m, dtype=np.float64)
        world_pos = self.rotation_matrix @ robot_pos + self.base_position
        return (float(world_pos[0]), float(world_pos[1]), float(world_pos[2]))

    def transformPose(
        self,
        world_position_m: Tuple[float, float, float],
        world_quat_wxyz: Tuple[float, float, float, float],
    ) -> PoseTarget:
        robot_position = self.transformPosition(world_position_m)

        w, x, y, z = world_quat_wxyz
        world_rot = quatWxyzToRotationMatrix(w, x, y, z)
        robot_rot = self.rotation_matrix_inv @ world_rot
        robot_quat = rotationMatrixToQuatWxyz(robot_rot)

        return PoseTarget(
            position_m=robot_position,
            quat_wxyz=robot_quat,
        )

    @classmethod
    def fromRobotDefinition(cls, robot_definition) -> "WorldToRobotBaseTransform":
        return cls(
            base_position_m=tuple(robot_definition.base_position_m),
            base_quat_wxyz=tuple(robot_definition.base_quat_wxyz),
        )


