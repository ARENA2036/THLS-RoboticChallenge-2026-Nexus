"""
Time-stepped viewer playback loop for board setup and combined assembly.
"""

from __future__ import annotations

import time
from typing import List

from simulation.examples.board_setup.OverlayEventAdapter import (
    processOverlayEvents,
    processWireRoutingOverlayEvents,
    updateCarriedObjectsToTcp,
)
from simulation.interface.RobotHardwareProtocol import RobotHardwareInterface
from simulation.planning.BoardSetupExecutor import BoardSetupResult, OverlayEvent
from simulation.planning.WireRoutingExecutor import WireRoutingOverlayEvent
from simulation.visualization.SceneObjectOverlay import SceneObjectOverlay

try:
    import mujoco
    import mujoco.viewer
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore


def _buildTcpSiteIds(scene_runtime) -> dict:
    """Resolve TCP site MuJoCo IDs for all robots."""
    tcp_site_ids: dict = {}
    for robot_name, site_name in scene_runtime.robot_tcp_sites.items():
        site_id = mujoco.mj_name2id(
            scene_runtime.model, mujoco.mjtObj.mjOBJ_SITE, site_name,
        )
        if site_id >= 0:
            tcp_site_ids[robot_name] = site_id
    return tcp_site_ids


def _launchViewerLoop(
    scene_runtime,
    hardware_interface: RobotHardwareInterface,
    scene_overlay: SceneObjectOverlay,
    total_playback_s: float,
    board_setup_events: List[OverlayEvent],
    wire_routing_events: List[WireRoutingOverlayEvent],
    is_keep_open: bool,
) -> None:
    """Core viewer loop shared by board-setup-only and combined playback."""
    processed_board_indices: set = set()
    processed_routing_indices: set = set()
    tcp_site_ids = _buildTcpSiteIds(scene_runtime)

    padded_duration = total_playback_s + 2.0

    with mujoco.viewer.launch_passive(scene_runtime.model, scene_runtime.data) as viewer:
        viewer.opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = False
        viewer.opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTFORCE] = False
        viewer.opt.frame = mujoco.mjtFrame.mjFRAME_NONE

        viewer.cam.azimuth = 150.0
        viewer.cam.elevation = -35.0
        viewer.cam.distance = 4.5
        viewer.cam.lookat[:] = [0.0, 0.0, 0.85]

        wall_start = time.time()

        while viewer.is_running():
            wall_elapsed = time.time() - wall_start

            if not is_keep_open and wall_elapsed >= padded_duration:
                break

            if wall_elapsed < padded_duration:
                hardware_interface.stepToTimestamp(wall_elapsed)

            current_sim_time = hardware_interface.getCurrentTimestamp()

            processOverlayEvents(
                scene_overlay, board_setup_events,
                current_sim_time, processed_board_indices,
            )
            processWireRoutingOverlayEvents(
                scene_overlay, wire_routing_events,
                current_sim_time, processed_routing_indices,
            )
            updateCarriedObjectsToTcp(scene_overlay, scene_runtime, tcp_site_ids)

            if viewer.user_scn is not None:
                viewer.user_scn.ngeom = 0
                scene_overlay.renderAll(viewer.user_scn)

            viewer.sync()
            time.sleep(0.008)


def runViewerLoop(
    scene_runtime,
    hardware_interface: RobotHardwareInterface,
    scene_overlay: SceneObjectOverlay,
    setup_result: BoardSetupResult,
    is_keep_open: bool,
) -> None:
    """Drive the MuJoCo viewer forward at wall-clock pace (board setup only)."""
    _launchViewerLoop(
        scene_runtime=scene_runtime,
        hardware_interface=hardware_interface,
        scene_overlay=scene_overlay,
        total_playback_s=setup_result.total_duration_s,
        board_setup_events=setup_result.overlay_events,
        wire_routing_events=[],
        is_keep_open=is_keep_open,
    )


def runCombinedViewerLoop(
    scene_runtime,
    hardware_interface: RobotHardwareInterface,
    scene_overlay: SceneObjectOverlay,
    total_playback_s: float,
    board_setup_events: List[OverlayEvent],
    wire_routing_events: List[WireRoutingOverlayEvent],
    is_keep_open: bool,
) -> None:
    """Unified viewer loop for board setup followed by wire routing."""
    _launchViewerLoop(
        scene_runtime=scene_runtime,
        hardware_interface=hardware_interface,
        scene_overlay=scene_overlay,
        total_playback_s=total_playback_s,
        board_setup_events=board_setup_events,
        wire_routing_events=wire_routing_events,
        is_keep_open=is_keep_open,
    )
