"""
Full assembly simulation -- board setup followed by wire routing.

Thin CLI wrapper that orchestrates:
  1. Board setup (peg/connector placement) -- can be skipped by loading
     a saved snapshot.
  2. Wire routing (dual-arm independent-pace middle-out traversal with
     mocked insertion and pull-test).

Usage:
    python -m simulation.examples.run_full_assembly \
        --cdm-file public/cdm/examples/simple_harness.json \
        --viewer --keep-open

    python -m simulation.examples.run_full_assembly \
        --cdm-file public/cdm/examples/simple_harness.json \
        --load-snapshot /tmp/board_snapshot.json \
        --viewer
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.ConfigModels import WireRoutingConfig
from simulation.core.CoordinateTransform import AxisMapping, BoardToWorldTransform, WorldToRobotBaseTransform
from simulation.core.SnapshotIO import loadSnapshot, saveSnapshot
from simulation.examples.board_setup.BoardSetupRunner import (
    buildSimulationStack,
    runBoardSetup,
)
from simulation.examples.ViewerSupport import probe_viewer_support
from simulation.interface.CameraMockService import CameraMockServiceImpl
from simulation.interface.ForceTorqueMockService import ForceTorqueMockServiceImpl
from simulation.planning.BoardSetupExecutor import BoardSetupResult, OverlayEvent, OverlayEventType
from simulation.planning.LayoutToSimulationBridge import (
    generateLayout,
    generateMotionPlans,
    loadHarnessFromJson,
)
from simulation.planning.MiddleOutPlanner import splitPegsMiddleOut
from simulation.planning.MotionSequenceBuilder import MotionSequenceBuilder
from simulation.planning.TrajectoryCollisionChecker import SharedAreaPolicy, TrajectoryCollisionChecker
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WireRoutingExecutor import (
    WireRoutingExecutor,
    WireRoutingOverlayEvent,
    WireRoutingStepResult,
)
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator
from simulation.visualization.SceneObjectOverlay import SceneObjectOverlay

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPModels import PhaseType, ProcessType, RouteWireParameters

logger = logging.getLogger(__name__)

_DEFAULT_WIRE_COLOR = (0.95, 0.55, 0.1, 1.0)

_WIRE_COLOR_LOOKUP: Dict[str, Tuple[float, float, float, float]] = {
    "RD": (0.9, 0.1, 0.1, 1.0),
    "BU": (0.1, 0.3, 0.9, 1.0),
    "BK": (0.1, 0.1, 0.1, 1.0),
    "WH": (0.95, 0.95, 0.95, 1.0),
    "GN": (0.1, 0.7, 0.2, 1.0),
    "YE": (0.9, 0.85, 0.1, 1.0),
    "OG": (0.95, 0.55, 0.1, 1.0),
    "VT": (0.6, 0.1, 0.8, 1.0),
    "BN": (0.5, 0.3, 0.1, 1.0),
    "GY": (0.5, 0.5, 0.5, 1.0),
}


def resolveWireColor(
    wire_cover_colors: list,
    wire_routing_config: WireRoutingConfig,
) -> Tuple[float, float, float, float]:
    """Derive wire RGBA from CDM cover_colors, falling back to config defaults."""
    for cover_color in wire_cover_colors:
        color_code = getattr(cover_color, "color_code", None) if not isinstance(cover_color, dict) else cover_color.get("color_code")
        if color_code and color_code in wire_routing_config.wire_color_map:
            return tuple(wire_routing_config.wire_color_map[color_code])
        if color_code and color_code in _WIRE_COLOR_LOOKUP:
            return _WIRE_COLOR_LOOKUP[color_code]
    return tuple(wire_routing_config.default_wire_color)


def runFullAssembly(
    cdm_file: str,
    use_viewer: bool = False,
    force_viewer: bool = False,
    keep_open: bool = False,
    load_snapshot_path: str | None = None,
    save_snapshot_path: str | None = None,
) -> bool:
    """Execute board setup + wire routing end-to-end."""
    print("=" * 60)
    print("Full Assembly Simulation")
    print("=" * 60)

    simulation_root = Path(__file__).resolve().parent.parent
    config_loader = ConfigLoader(str(simulation_root))

    board_setup_config = config_loader.load_board_setup_config()
    wire_routing_config = config_loader.load_wire_routing_config()

    harness = loadHarnessFromJson(cdm_file)
    print(f"Harness: {harness.id} ({harness.part_number})")

    layout_result = generateLayout(
        harness,
        cdm_file_path=cdm_file,
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
    )

    scene_runtime, hardware_interface, planner_client, planner_transport, station_config, robots_config = (
        buildSimulationStack(config_loader)
    )

    axis_mapping = AxisMapping(
        layout_x_to_world=board_setup_config.axis_mapping.layout_x_to_world,
        layout_y_to_world=board_setup_config.axis_mapping.layout_y_to_world,
    )
    board_transform = BoardToWorldTransform.fromConfigs(
        station_config,
        layout_board_width_mm=layout_result.board_width_mm,
        layout_board_height_mm=layout_result.board_height_mm,
        board_center_offset_mm=board_setup_config.board_center_offset_mm,
        axis_mapping=axis_mapping,
    )

    scene_overlay = SceneObjectOverlay()
    setup_result: BoardSetupResult | None = None
    board_setup_overlay_events: List[OverlayEvent] = []
    board_setup_duration_s: float = 0.0

    # ------------------------------------------------------------------
    # Phase 1: Board Setup (or load snapshot)
    # ------------------------------------------------------------------
    if load_snapshot_path:
        print(f"\n[1] Loading board setup snapshot from: {load_snapshot_path}")
        snapshot = loadSnapshot(load_snapshot_path)
        for event in snapshot.overlay_events:
            if event.event_type == OverlayEventType.PLACE_OBJECT:
                scene_overlay.addCarriedObject(
                    object_id=event.object_id,
                    object_type=event.object_type,
                    position_m=event.position_m,
                    orientation_deg=event.orientation_deg,
                )
                scene_overlay.placeObject(
                    object_id=event.object_id,
                    position_m=event.position_m,
                    orientation_deg=event.orientation_deg,
                )
        print(f"    Restored {len(snapshot.overlay_events)} overlay events")
    else:
        print("\n[1] Running board setup...")
        setup_result = runBoardSetup(
            cdm_file=cdm_file,
            use_viewer=False,
            force_viewer=False,
            keep_open=False,
        )
        if not setup_result.success:
            print("Board setup FAILED. Aborting assembly.")
            return False

        board_setup_overlay_events = list(setup_result.overlay_events)
        board_setup_duration_s = setup_result.total_duration_s

        for event in setup_result.overlay_events:
            if event.event_type == OverlayEventType.PLACE_OBJECT:
                scene_overlay.addCarriedObject(
                    object_id=event.object_id,
                    object_type=event.object_type,
                    position_m=event.position_m,
                    orientation_deg=event.orientation_deg,
                )
                scene_overlay.placeObject(
                    object_id=event.object_id,
                    position_m=event.position_m,
                    orientation_deg=event.orientation_deg,
                )

        if save_snapshot_path:
            home_joints = {
                robot_def.robot_name: list(robot_def.home_joint_angles_rad)
                for robot_def in robots_config.robots
            }
            saveSnapshot(save_snapshot_path, setup_result.overlay_events, home_joints)
            print(f"    Snapshot saved to: {save_snapshot_path}")

    # ------------------------------------------------------------------
    # Phase 2: Wire Routing
    # ------------------------------------------------------------------
    print("\n[2] Preparing wire routing...")

    bop_config = BoPGeneratorConfig(
        production_id="sim_full_assembly",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_result.response,
                station_id="assembly_station_1",
            ),
        ],
    )
    bop_service = BoPGeneratorService()
    production_bop = bop_service.generate(bop_config)

    wire_routing_phase = None
    for phase in production_bop.phases:
        if phase.phase_type == PhaseType.WIRE_ROUTING:
            wire_routing_phase = phase
            break

    if wire_routing_phase is None or not wire_routing_phase.steps:
        print("    No WIRE_ROUTING phase found. Assembly complete (board setup only).")
        return True

    route_wire_steps = [
        step for step in wire_routing_phase.steps
        if step.process_type == ProcessType.ROUTE_WIRE
    ]
    print(f"    Found {len(route_wire_steps)} ROUTE_WIRE steps")

    robot_base_positions = {
        robot_def.robot_name: tuple(robot_def.base_position_m)
        for robot_def in robots_config.robots
    }
    robot_base_transforms = {
        robot_def.robot_name: WorldToRobotBaseTransform.fromRobotDefinition(robot_def)
        for robot_def in robots_config.robots
    }
    home_joint_angles_by_robot = {
        robot_def.robot_name: list(robot_def.home_joint_angles_rad)
        for robot_def in robots_config.robots
    }

    trajectory_store = TrajectoryStore()
    coordinator = WorkspaceCoordinator(
        robot_names=[r.robot_name for r in robots_config.robots],
        robot_base_positions=robot_base_positions,
        pickup_clearance_radius_m=board_setup_config.pickup_clearance_radius_m,
        trajectory_store=trajectory_store,
    )
    for robot_name in home_joint_angles_by_robot:
        coordinator.notifyAtHome(robot_name, 0.0)

    motion_builders = {
        robot_name: MotionSequenceBuilder(
            hardware=hardware_interface,
            planner=planner_client,
        )
        for robot_name in home_joint_angles_by_robot
    }

    camera_mock = CameraMockServiceImpl()
    force_mock = ForceTorqueMockServiceImpl()

    routing_executor = WireRoutingExecutor(
        motion_builders=motion_builders,
        coordinator=coordinator,
        robot_base_transforms=robot_base_transforms,
        camera_service=camera_mock,
        force_torque_service=force_mock,
        wire_routing_config=wire_routing_config,
        home_joint_angles_by_robot=home_joint_angles_by_robot,
        robot_base_positions=robot_base_positions,
    )

    peg_positions_world = _buildPegPositionsWorld(layout_result.response, board_transform)
    peg_orientations_world = _buildPegOrientationsWorld(layout_result.response, board_transform)
    connector_positions_world = _buildConnectorPositionsWorld(layout_result.response, board_transform)
    connector_orientations_world = _buildConnectorOrientationsWorld(layout_result.response, board_transform)
    board_surface_z = board_transform.getBoardSurfaceZ()

    connection_lookup = {conn.id: conn for conn in harness.connections}

    all_routing_events: List[WireRoutingOverlayEvent] = []
    routed_count = 0
    failed_count = 0

    for step_index, step in enumerate(route_wire_steps, start=1):
        route_params: RouteWireParameters = step.parameters
        print(f"\n    [{step_index}/{len(route_wire_steps)}] Routing wire {route_params.wire_occurrence_id}...")

        connection = connection_lookup.get(route_params.connection_id)
        wire_color = _DEFAULT_WIRE_COLOR
        wire_cross_section = 0.5
        if connection is not None:
            wire = connection.wire_occurrence.wire
            wire_color = resolveWireColor(
                getattr(wire, "cover_colors", []),
                wire_routing_config,
            )
            wire_cross_section = getattr(wire, "cross_section_area_mm2", 0.5) or 0.5

        extremity_connector_ids = [
            ext.connector_occurrence_id for ext in route_params.extremities
        ]

        result = routing_executor.executeRouteWire(
            wire_occurrence_id=route_params.wire_occurrence_id,
            connection_id=route_params.connection_id,
            ordered_peg_ids=route_params.ordered_peg_ids,
            peg_positions_world=peg_positions_world,
            peg_orientations_world=peg_orientations_world,
            extremity_connector_ids=extremity_connector_ids,
            connector_positions_world=connector_positions_world,
            connector_orientations_world=connector_orientations_world,
            wire_color_rgba=wire_color,
            wire_cross_section_mm2=wire_cross_section,
            board_surface_z=board_surface_z,
        )

        all_routing_events.extend(result.overlay_events)

        if result.success:
            routed_count += 1
            print(f"      OK ({len(result.routed_segments)} segments)")
        else:
            failed_count += 1
            print(f"      FAILED: {result.error_message}")

        force_mock.resetRamp()

    print(f"\n[3] Wire routing complete: {routed_count} succeeded, {failed_count} failed")

    routing_end_time = max(
        (coordinator.getRobotState(rn).current_time_s for rn in home_joint_angles_by_robot),
        default=0.0,
    )
    total_time = board_setup_duration_s + routing_end_time

    if use_viewer:
        is_supported, reason_message = probe_viewer_support()
        if is_supported or force_viewer:
            print("\n[4] Launching combined viewer...")
            from simulation.examples.board_setup.ViewerPlaybackLoop import runCombinedViewerLoop
            runCombinedViewerLoop(
                scene_runtime=scene_runtime,
                hardware_interface=hardware_interface,
                scene_overlay=scene_overlay,
                total_playback_s=total_time,
                board_setup_events=board_setup_overlay_events,
                wire_routing_events=all_routing_events,
                is_keep_open=keep_open,
            )
        else:
            print(f"Viewer disabled: {reason_message}")
            hardware_interface.stepToTimestamp(total_time)
    else:
        print("\n[4] Running headless...")
        hardware_interface.stepToTimestamp(total_time)

    print("\n" + "=" * 60)
    print(f"Full assembly COMPLETE: {routed_count}/{len(route_wire_steps)} wires routed.")
    print("=" * 60)

    return failed_count == 0


def _buildPegPositionsWorld(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, Tuple[float, float, float]]:
    """Convert layout peg positions to world coordinates."""
    positions: Dict[str, Tuple[float, float, float]] = {}
    for peg in layout_response.pegs:
        world_pos = board_transform.transformToWorld(peg.position.x, peg.position.y)
        positions[peg.id] = world_pos
    return positions


def _buildPegOrientationsWorld(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, float]:
    """Convert layout peg orientations to world-frame angles (degrees)."""
    orientations: Dict[str, float] = {}
    for peg in layout_response.pegs:
        layout_deg = getattr(peg, "orientation_deg", 0.0)
        world_deg = board_transform.axis_mapping.transformOrientationDeg(layout_deg)
        orientations[peg.id] = world_deg
    return orientations


def _buildConnectorPositionsWorld(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, Tuple[float, float, float]]:
    """Convert layout connector holder positions to world coordinates."""
    positions: Dict[str, Tuple[float, float, float]] = {}
    for holder in layout_response.connector_holders:
        world_pos = board_transform.transformToWorld(holder.position.x, holder.position.y)
        positions[holder.connector_id] = world_pos
    return positions


def _buildConnectorOrientationsWorld(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, float]:
    """Convert layout connector orientations to world-frame angles (degrees)."""
    orientations: Dict[str, float] = {}
    for holder in layout_response.connector_holders:
        layout_deg = getattr(holder, "orientation_deg", 0.0)
        world_deg = board_transform.axis_mapping.transformOrientationDeg(layout_deg)
        orientations[holder.connector_id] = world_deg
    return orientations


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Full assembly simulation: board setup + wire routing.",
    )
    parser.add_argument(
        "--cdm-file", type=str, required=True,
        help="Path to CDM wire harness JSON file.",
    )
    parser.add_argument("--viewer", action="store_true", help="Launch MuJoCo viewer.")
    parser.add_argument("--force-viewer", action="store_true", help="Bypass viewer checks.")
    parser.add_argument("--keep-open", action="store_true", help="Keep viewer open after execution.")
    parser.add_argument(
        "--load-snapshot", type=str, default=None,
        help="Path to a board-setup snapshot JSON to skip board setup.",
    )
    parser.add_argument(
        "--save-snapshot", type=str, default=None,
        help="Path to save board-setup snapshot JSON after board setup.",
    )
    args = parser.parse_args()

    success = runFullAssembly(
        cdm_file=args.cdm_file,
        use_viewer=args.viewer,
        force_viewer=args.force_viewer,
        keep_open=args.keep_open,
        load_snapshot_path=args.load_snapshot,
        save_snapshot_path=args.save_snapshot,
    )

    os._exit(0 if success else 1)


if __name__ == "__main__":
    main()
