"""
Dynamic scene object overlay for carried and placed objects.

Renders peg and connector-holder shapes into the MuJoCo viewer's
user_scn overlay.  Objects can be in one of two states:

  - Carried: position updated each frame to follow the robot TCP.
  - Placed:  position fixed at the board placement location.

Uses the same mjv_initGeom API as PathRenderer, appending geoms
starting from the current user_scene.ngeom (no reset).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from simulation.core.RotationUtils import rotateOffsetAroundZ, zRotationMatrixFlat

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore

logger = logging.getLogger(__name__)

_IDENTITY_MAT_FLAT = np.eye(3, dtype=np.float64).flatten()
_ZEROS_3 = np.zeros(3, dtype=np.float64)


class ObjectVisualState(StrEnum):
    CARRIED = "CARRIED"
    PLACED = "PLACED"


@dataclass
class OverlayObjectState:
    object_id: str
    object_type: str
    visual_state: ObjectVisualState
    position_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    color_rgba: Tuple[float, float, float, float] = (0.72, 0.72, 0.74, 1.0)
    size_params: Dict = field(default_factory=dict)
    robot_name: str = ""
    orientation_deg: float = 0.0


_PEG_DEFAULT_COLOR = np.array([0.72, 0.72, 0.74, 1.0], dtype=np.float32)
_HOLDER_DEFAULT_COLOR = np.array([0.2, 0.42, 0.86, 1.0], dtype=np.float32)


class SceneObjectOverlay:
    """Manages carried and placed object overlays in user_scn."""

    def __init__(self) -> None:
        self._objects: Dict[str, OverlayObjectState] = {}
        self._geom_cap_warned = False
        self._renderers: Dict[str, Callable[["mujoco.MjvScene", OverlayObjectState], None]] = {
            "peg": self._renderPeg,
            "connector_holder": self._renderHolder,
            "cable_end": self._renderCableEnd,
            "carried_cable": self._renderCarriedCable,
            "routed_cable_segment": self._renderRoutedCableSegment,
        }

    def addCarriedObject(
        self,
        object_id: str,
        object_type: str,
        position_m: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        color_rgba: Tuple[float, float, float, float] | None = None,
        size_params: Dict | None = None,
        robot_name: str = "",
        orientation_deg: float = 0.0,
    ) -> None:
        if color_rgba is None:
            color_rgba = (0.72, 0.72, 0.74, 1.0) if object_type == "peg" else (0.2, 0.42, 0.86, 1.0)

        self._objects[object_id] = OverlayObjectState(
            object_id=object_id,
            object_type=object_type,
            visual_state=ObjectVisualState.CARRIED,
            position_m=position_m,
            color_rgba=color_rgba,
            size_params=size_params or {},
            robot_name=robot_name,
            orientation_deg=orientation_deg,
        )

    def updateCarriedObjectPose(
        self,
        object_id: str,
        position_m: Tuple[float, float, float],
        orientation_deg: float | None = None,
    ) -> None:
        obj_state = self._objects.get(object_id)
        if obj_state is None or obj_state.visual_state != ObjectVisualState.CARRIED:
            return
        obj_state.position_m = position_m
        if orientation_deg is not None:
            obj_state.orientation_deg = orientation_deg

    def placeObject(
        self,
        object_id: str,
        position_m: Tuple[float, float, float],
        orientation_deg: float | None = None,
    ) -> None:
        obj_state = self._objects.get(object_id)
        if obj_state is None:
            return
        obj_state.visual_state = ObjectVisualState.PLACED
        obj_state.position_m = position_m
        if orientation_deg is not None:
            obj_state.orientation_deg = orientation_deg

    def removeObject(self, object_id: str) -> None:
        self._objects.pop(object_id, None)

    def getPlacedObjects(self) -> List[OverlayObjectState]:
        return [
            obj for obj in self._objects.values()
            if obj.visual_state == ObjectVisualState.PLACED
        ]

    def getCarriedObjects(self) -> List[OverlayObjectState]:
        return [
            obj for obj in self._objects.values()
            if obj.visual_state == ObjectVisualState.CARRIED
        ]

    def registerRenderer(
        self,
        object_type: str,
        renderer: Callable[["mujoco.MjvScene", OverlayObjectState], None],
    ) -> None:
        """Register a new renderer for a given object type (e.g. 'cable_segment')."""
        self._renderers[object_type] = renderer

    def renderAll(self, user_scene: "mujoco.MjvScene") -> None:
        if mujoco is None or user_scene is None:
            return

        self._geom_cap_warned = False

        for obj_state in self._objects.values():
            renderer = self._renderers.get(obj_state.object_type)
            if renderer is not None:
                renderer(user_scene, obj_state)

    def _renderPeg(
        self,
        user_scene: "mujoco.MjvScene",
        obj_state: OverlayObjectState,
    ) -> None:
        foot_half_size = obj_state.size_params.get("foot_half_size_m", 0.018)
        foot_half_height = obj_state.size_params.get("foot_half_height_m", 0.005)
        post_radius = obj_state.size_params.get("post_radius_m", 0.007)
        post_height = obj_state.size_params.get("post_height_m", 0.045)
        crossbar_half_span = obj_state.size_params.get("crossbar_half_span_m", 0.020)
        crossbar_half_thickness = obj_state.size_params.get("crossbar_half_thickness_m", 0.004)
        crossbar_half_depth = obj_state.size_params.get("crossbar_half_depth_m", 0.004)
        prong_radius = obj_state.size_params.get("prong_radius_m", 0.005)
        prong_height = obj_state.size_params.get("prong_height_m", 0.030)

        # The peg crossbar spans along local Y, which is 90deg in the
        # layout generator's angle convention (0deg = +X).  Subtract 90
        # so that orientation_deg=90 keeps the crossbar along Y.
        angle_deg = obj_state.orientation_deg - 90.0
        rot_mat = zRotationMatrixFlat(angle_deg)

        base_pos = np.array(obj_state.position_m, dtype=np.float64)
        foot_rgba = np.array([0.25, 0.25, 0.28, 1.0], dtype=np.float32)
        post_rgba = np.array(obj_state.color_rgba, dtype=np.float32)
        crossbar_rgba = np.array(obj_state.color_rgba, dtype=np.float32)
        crossbar_rgba[:3] *= 0.85
        prong_rgba = np.array(obj_state.color_rgba, dtype=np.float32)
        prong_rgba[:3] *= 0.90

        foot_top = foot_half_height * 2.0
        post_base_z = foot_top
        crossbar_z = post_base_z + post_height + crossbar_half_thickness

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([foot_half_size, foot_half_size, foot_half_height], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, foot_half_height]), angle_deg),
            mat=rot_mat,
            rgba=foot_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=np.array([post_radius, post_height / 2.0, 0.0], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, post_base_z + post_height / 2.0]), angle_deg),
            mat=rot_mat,
            rgba=post_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([crossbar_half_depth, crossbar_half_span, crossbar_half_thickness], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, crossbar_z]), angle_deg),
            mat=rot_mat,
            rgba=crossbar_rgba,
        )
        user_scene.ngeom += 1

        prong_base_z = crossbar_z + crossbar_half_thickness
        for side_sign in (-1.0, 1.0):
            if not self._hasGeomBudget(user_scene):
                return
            prong_y_offset = side_sign * crossbar_half_span
            mujoco.mjv_initGeom(
                user_scene.geoms[user_scene.ngeom],
                type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                size=np.array([prong_radius, prong_height / 2.0, 0.0], dtype=np.float64),
                pos=base_pos + rotateOffsetAroundZ(np.array([0.0, prong_y_offset, prong_base_z + prong_height / 2.0]), angle_deg),
                mat=rot_mat,
                rgba=prong_rgba,
            )
            user_scene.ngeom += 1

    def _renderHolder(
        self,
        user_scene: "mujoco.MjvScene",
        obj_state: OverlayObjectState,
    ) -> None:
        foot_half_size = obj_state.size_params.get("holder_foot_half_size_m", 0.022)
        foot_half_height = obj_state.size_params.get("holder_foot_half_height_m", 0.005)
        pedestal_half_width = obj_state.size_params.get("pedestal_half_width_m", 0.012)
        pedestal_half_depth = obj_state.size_params.get("pedestal_half_depth_m", 0.012)
        pedestal_half_height = obj_state.size_params.get("pedestal_half_height_m", 0.022)
        connector_half_width = obj_state.size_params.get("connector_half_width_m", 0.016)
        connector_half_depth = obj_state.size_params.get("connector_half_depth_m", 0.010)
        connector_half_height = obj_state.size_params.get("connector_half_height_m", 0.008)

        angle_deg = obj_state.orientation_deg
        rot_mat = zRotationMatrixFlat(angle_deg)

        base_pos = np.array(obj_state.position_m, dtype=np.float64)
        foot_rgba = np.array([0.25, 0.25, 0.28, 1.0], dtype=np.float32)
        pedestal_rgba = np.array([0.92, 0.92, 0.92, 1.0], dtype=np.float32)
        connector_rgba = np.array(obj_state.color_rgba, dtype=np.float32)

        foot_top = foot_half_height * 2.0
        pedestal_top = foot_top + pedestal_half_height * 2.0

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([foot_half_size, foot_half_size, foot_half_height], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, foot_half_height]), angle_deg),
            mat=rot_mat,
            rgba=foot_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([pedestal_half_width, pedestal_half_depth, pedestal_half_height], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, foot_top + pedestal_half_height]), angle_deg),
            mat=rot_mat,
            rgba=pedestal_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([connector_half_width, connector_half_depth, connector_half_height], dtype=np.float64),
            pos=base_pos + rotateOffsetAroundZ(np.array([0.0, 0.0, pedestal_top + connector_half_height]), angle_deg),
            mat=rot_mat,
            rgba=connector_rgba,
        )
        user_scene.ngeom += 1

    # ------------------------------------------------------------------
    # Cable / wire renderers
    # ------------------------------------------------------------------

    def _renderCableEnd(
        self,
        user_scene: "mujoco.MjvScene",
        obj_state: OverlayObjectState,
    ) -> None:
        """Render a cable hanging vertically from anchor to pickup (crimp at bottom)."""
        cable_radius = obj_state.size_params.get("cable_radius_m", 0.003)
        crimp_half_w = obj_state.size_params.get("crimp_half_width_m", 0.004)
        crimp_half_h = obj_state.size_params.get("crimp_half_height_m", 0.006)
        crimp_half_d = obj_state.size_params.get("crimp_half_depth_m", 0.003)

        pickup_pos = np.array(obj_state.position_m, dtype=np.float64)

        anchor_raw = obj_state.size_params.get("anchor_position_m")
        if anchor_raw is not None:
            anchor_pos = np.array(anchor_raw, dtype=np.float64)
        else:
            anchor_pos = pickup_pos + np.array([0.0, 0.0, 0.30], dtype=np.float64)

        hang_vector = pickup_pos - anchor_pos
        hang_length = float(np.linalg.norm(hang_vector))
        if hang_length < 1e-6:
            hang_length = 0.30
            anchor_pos = pickup_pos + np.array([0.0, 0.0, hang_length], dtype=np.float64)

        mid_point = (anchor_pos + pickup_pos) / 2.0

        wire_rgba = np.array(obj_state.color_rgba, dtype=np.float32)
        crimp_rgba = np.array([0.7, 0.7, 0.7, 1.0], dtype=np.float32)

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=np.array([cable_radius, hang_length / 2.0, 0.0], dtype=np.float64),
            pos=mid_point,
            mat=_IDENTITY_MAT_FLAT.copy(),
            rgba=wire_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([crimp_half_w, crimp_half_d, crimp_half_h], dtype=np.float64),
            pos=pickup_pos + np.array([0.0, 0.0, -crimp_half_h], dtype=np.float64),
            mat=_IDENTITY_MAT_FLAT.copy(),
            rgba=crimp_rgba,
        )
        user_scene.ngeom += 1

    def _renderCarriedCable(
        self,
        user_scene: "mujoco.MjvScene",
        obj_state: OverlayObjectState,
    ) -> None:
        """Render a stiff cable segment hanging from TCP + crimp at tip."""
        cable_radius = obj_state.size_params.get("cable_radius_m", 0.003)
        cable_hang_length = obj_state.size_params.get("cable_hang_length_m", 0.08)
        crimp_half_w = obj_state.size_params.get("crimp_half_width_m", 0.004)
        crimp_half_h = obj_state.size_params.get("crimp_half_height_m", 0.006)
        crimp_half_d = obj_state.size_params.get("crimp_half_depth_m", 0.003)

        base_pos = np.array(obj_state.position_m, dtype=np.float64)
        wire_rgba = np.array(obj_state.color_rgba, dtype=np.float32)
        crimp_rgba = np.array([0.7, 0.7, 0.7, 1.0], dtype=np.float32)

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=np.array([cable_radius, cable_hang_length / 2.0, 0.0], dtype=np.float64),
            pos=base_pos + np.array([0.0, 0.0, -cable_hang_length / 2.0], dtype=np.float64),
            mat=_IDENTITY_MAT_FLAT.copy(),
            rgba=wire_rgba,
        )
        user_scene.ngeom += 1

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=np.array([crimp_half_w, crimp_half_d, crimp_half_h], dtype=np.float64),
            pos=base_pos + np.array([0.0, 0.0, -cable_hang_length - crimp_half_h], dtype=np.float64),
            mat=_IDENTITY_MAT_FLAT.copy(),
            rgba=crimp_rgba,
        )
        user_scene.ngeom += 1

    def _renderRoutedCableSegment(
        self,
        user_scene: "mujoco.MjvScene",
        obj_state: OverlayObjectState,
    ) -> None:
        """Render a placed cable segment as a capsule between two peg positions.

        ``size_params`` must contain ``start_position_m`` and ``end_position_m``
        as 3-tuples.
        """
        start_raw = obj_state.size_params.get("start_position_m", (0.0, 0.0, 0.0))
        end_raw = obj_state.size_params.get("end_position_m", (0.0, 0.0, 0.0))
        cable_radius = obj_state.size_params.get("cable_radius_m", 0.003)

        start_pos = np.array(start_raw, dtype=np.float64)
        end_pos = np.array(end_raw, dtype=np.float64)
        mid_point = (start_pos + end_pos) / 2.0
        diff = end_pos - start_pos
        segment_length = float(np.linalg.norm(diff))

        if segment_length < 1e-6:
            return

        direction = diff / segment_length
        world_z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        if abs(np.dot(direction, world_z)) > 0.999:
            rot_mat = _IDENTITY_MAT_FLAT.copy()
        else:
            axis = np.cross(world_z, direction)
            axis_norm = float(np.linalg.norm(axis))
            if axis_norm < 1e-9:
                rot_mat = _IDENTITY_MAT_FLAT.copy()
            else:
                axis /= axis_norm
                cos_angle = float(np.dot(world_z, direction))
                sin_angle = axis_norm
                skew = np.array([
                    [0, -axis[2], axis[1]],
                    [axis[2], 0, -axis[0]],
                    [-axis[1], axis[0], 0],
                ], dtype=np.float64)
                rotation_matrix = (
                    np.eye(3, dtype=np.float64)
                    + sin_angle * skew
                    + (1 - cos_angle) * (skew @ skew)
                )
                rot_mat = rotation_matrix.flatten()

        wire_rgba = np.array(obj_state.color_rgba, dtype=np.float32)

        if not self._hasGeomBudget(user_scene):
            return
        mujoco.mjv_initGeom(
            user_scene.geoms[user_scene.ngeom],
            type=mujoco.mjtGeom.mjGEOM_CAPSULE,
            size=np.array([cable_radius, segment_length / 2.0, 0.0], dtype=np.float64),
            pos=mid_point,
            mat=rot_mat,
            rgba=wire_rgba,
        )
        user_scene.ngeom += 1

    def _hasGeomBudget(self, user_scene: "mujoco.MjvScene") -> bool:
        if user_scene.ngeom >= user_scene.maxgeom:
            if not self._geom_cap_warned:
                logger.warning(
                    "Overlay geom budget exhausted (%d geoms). "
                    "Some objects will not be rendered.",
                    user_scene.maxgeom,
                )
                self._geom_cap_warned = True
            return False
        return True
