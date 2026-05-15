"""
MuJoCo viewer overlay renderer for recorded TCP path segments.

Injects capsule geoms into the viewer's user_scn so they are
composited on top of the physics scene each frame.
"""

import logging
from typing import List

import numpy as np

from simulation.visualization.VisualizationModels import PathSegment

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore

logger = logging.getLogger(__name__)

_IDENTITY_MAT_FLAT = np.eye(3, dtype=np.float64).flatten()
_ZEROS_3 = np.zeros(3, dtype=np.float64)


class PathRenderer:
    """Renders PathSegment data as capsule tubes in the MuJoCo viewer overlay."""

    def __init__(self, min_render_distance_m: float = 0.0005) -> None:
        self.min_render_distance_m = min_render_distance_m
        self._geom_cap_warned = False

    def renderSegments(
        self,
        user_scene: "mujoco.MjvScene",
        segments: List[PathSegment],
        reset_geom_count: bool = False,
    ) -> None:
        if mujoco is None or user_scene is None:
            return

        if reset_geom_count:
            user_scene.ngeom = 0
        self._geom_cap_warned = False

        for segment in segments:
            if not segment.is_visible or len(segment.points) < 2:
                continue
            self._render_single_segment(user_scene, segment)

    def _render_single_segment(self, user_scene: "mujoco.MjvScene", segment: PathSegment) -> None:
        rgba = np.array(segment.color_rgba, dtype=np.float32)
        points_array = np.asarray(segment.points, dtype=np.float64)
        previous_rendered = points_array[0].copy()

        for point_index in range(1, len(points_array)):
            if user_scene.ngeom >= user_scene.maxgeom:
                if not self._geom_cap_warned:
                    logger.warning(
                        "Viewer geom budget exhausted (%d geoms). "
                        "Remaining path segments will not be rendered. "
                        "Increase min_render_distance_m to reduce geom count.",
                        user_scene.maxgeom,
                    )
                    self._geom_cap_warned = True
                return

            current_point = points_array[point_index]
            distance = np.linalg.norm(current_point - previous_rendered)

            if distance < self.min_render_distance_m:
                continue

            geom_index = user_scene.ngeom
            mujoco.mjv_initGeom(
                user_scene.geoms[geom_index],
                type=mujoco.mjtGeom.mjGEOM_CAPSULE,
                size=_ZEROS_3,
                pos=_ZEROS_3,
                mat=_IDENTITY_MAT_FLAT,
                rgba=rgba,
            )
            mujoco.mjv_connector(
                user_scene.geoms[geom_index],
                type=mujoco.mjtGeom.mjGEOM_CAPSULE,
                width=segment.tube_radius_m,
                from_=previous_rendered,
                to=current_point,
            )
            user_scene.ngeom += 1
            previous_rendered = current_point.copy()
