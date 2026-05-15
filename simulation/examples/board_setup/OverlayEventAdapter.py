"""
Overlay event processing and TCP-follow updates for the board setup viewer.
"""

from __future__ import annotations

from typing import List, Set

from simulation.core.RotationUtils import extractYawFromRotationMatrix
from simulation.planning.BoardSetupExecutor import OverlayEvent, OverlayEventType
from simulation.planning.WireRoutingExecutor import WireRoutingOverlayEvent
from simulation.visualization.SceneObjectOverlay import SceneObjectOverlay


def processOverlayEvents(
    scene_overlay: SceneObjectOverlay,
    overlay_events: List[OverlayEvent],
    current_sim_time_s: float,
    processed_event_indices: Set[int],
) -> None:
    """Apply all overlay events whose timestamp has been reached."""
    for event_index, event in enumerate(overlay_events):
        if event_index in processed_event_indices:
            continue
        if current_sim_time_s >= event.timestamp_s:
            if event.event_type == OverlayEventType.ADD_CARRIED:
                scene_overlay.addCarriedObject(
                    object_id=event.object_id,
                    object_type=event.object_type,
                    position_m=event.position_m,
                    robot_name=event.robot_name,
                    orientation_deg=event.orientation_deg,
                )
            elif event.event_type == OverlayEventType.PLACE_OBJECT:
                scene_overlay.placeObject(
                    object_id=event.object_id,
                    position_m=event.position_m,
                    orientation_deg=event.orientation_deg,
                )
            processed_event_indices.add(event_index)


def processWireRoutingOverlayEvents(
    scene_overlay: SceneObjectOverlay,
    routing_events: List[WireRoutingOverlayEvent],
    current_sim_time_s: float,
    processed_event_indices: Set[int],
) -> None:
    """Apply wire-routing overlay events whose timestamp has been reached."""
    for event_index, event in enumerate(routing_events):
        if event_index in processed_event_indices:
            continue
        if current_sim_time_s < event.timestamp_s:
            continue

        if event.event_type == "ADD_CABLE_END":
            scene_overlay.addCarriedObject(
                object_id=event.object_id,
                object_type=event.object_type,
                position_m=event.position_m,
                color_rgba=event.color_rgba,
                size_params=event.size_params,
            )
            scene_overlay.placeObject(
                object_id=event.object_id,
                position_m=event.position_m,
            )
        elif event.event_type == "REMOVE_CABLE_END":
            scene_overlay.removeObject(event.object_id)
        elif event.event_type == "ADD_CARRIED_CABLE":
            scene_overlay.addCarriedObject(
                object_id=event.object_id,
                object_type=event.object_type,
                position_m=event.position_m,
                robot_name=event.robot_name,
                color_rgba=event.color_rgba,
                size_params=event.size_params,
            )
        elif event.event_type == "REMOVE_CARRIED_CABLE":
            scene_overlay.removeObject(event.object_id)
        elif event.event_type == "ADD_ROUTED_SEGMENT":
            scene_overlay.addCarriedObject(
                object_id=event.object_id,
                object_type=event.object_type,
                position_m=event.position_m,
                color_rgba=event.color_rgba,
                size_params=event.size_params,
            )
            scene_overlay.placeObject(
                object_id=event.object_id,
                position_m=event.position_m,
            )

        processed_event_indices.add(event_index)


def updateCarriedObjectsToTcp(
    scene_overlay: SceneObjectOverlay,
    scene_runtime,
    tcp_site_ids: dict,
) -> None:
    """Move each carried object to its robot's current TCP position and orientation."""
    for carried_obj in scene_overlay.getCarriedObjects():
        site_id = tcp_site_ids.get(carried_obj.robot_name)
        if site_id is None:
            continue
        tcp_position = scene_runtime.data.site_xpos[site_id].copy()
        tcp_yaw_deg = extractYawFromRotationMatrix(scene_runtime.data.site_xmat[site_id])
        scene_overlay.updateCarriedObjectPose(
            carried_obj.object_id,
            position_m=(float(tcp_position[0]), float(tcp_position[1]), float(tcp_position[2])),
            orientation_deg=tcp_yaw_deg,
        )
