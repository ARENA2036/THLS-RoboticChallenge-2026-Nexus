import argparse
import logging
import os
import sys
import cv2
import mujoco
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
from simulation.examples.run_full_assembly import resolveWireColor, _buildPegPositionsWorld, _buildPegOrientationsWorld, _buildConnectorPositionsWorld, _buildConnectorOrientationsWorld

logger = logging.getLogger(__name__)

def _renderVideoLoop(
    scene_runtime,
    hardware_interface,
    scene_overlay,
    total_playback_s: float,
    board_setup_events: list,
    wire_routing_events: list,
    output_path: str = "assembly.mp4",
    fps: int = 30,
) -> None:
    from simulation.examples.board_setup.ViewerPlaybackLoop import _buildTcpSiteIds
    from simulation.examples.board_setup.OverlayEventAdapter import (
        processOverlayEvents,
        processWireRoutingOverlayEvents,
        updateCarriedObjectsToTcp,
    )
    
    tcp_site_ids = _buildTcpSiteIds(scene_runtime)
    renderer = mujoco.Renderer(scene_runtime.model, height=720, width=1280)
    
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.azimuth = 270.0
    cam.elevation = -35.0
    cam.distance = 2.5
    cam.lookat[:] = [0.0, 0.0, 0.85]
    
    opt = mujoco.MjvOption()
    mujoco.mjv_defaultOption(opt)
    opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = False
    opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTFORCE] = False
    opt.frame = mujoco.mjtFrame.mjFRAME_NONE

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (1280, 720))
    
    dt = 1.0 / fps
    current_time = 0.0
    
    processed_board_indices = set()
    processed_routing_indices = set()
    
    print(f"Rendering {total_playback_s:.1f}s of video to {output_path}...")
    
    while current_time <= total_playback_s + 2.0:
        hardware_interface.stepToTimestamp(current_time)
        sim_time = hardware_interface.getCurrentTimestamp()
        
        processOverlayEvents(
            scene_overlay, board_setup_events,
            sim_time, processed_board_indices,
        )
        processWireRoutingOverlayEvents(
            scene_overlay, wire_routing_events,
            sim_time, processed_routing_indices,
        )
        updateCarriedObjectsToTcp(scene_overlay, scene_runtime, tcp_site_ids)
        
        renderer.update_scene(scene_runtime.data, camera=cam, scene_option=opt)
        scene_overlay.renderAll(renderer.scene)
        
        frame = renderer.render()
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        out.write(bgr_frame)
        
        current_time += dt
        
    out.release()
    renderer.close()
    print(f"Render complete! Saved to {output_path}")


def runFullAssemblyAndRender(
    cdm_file: str,
    output_path: str,
    load_snapshot_path: str | None = None,
    save_snapshot_path: str | None = None,
    board_setup_only: bool = False,
) -> bool:
    print("=" * 60)
    print("Full Assembly Simulation -> MP4 Video")
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
            step_headless=False,
            hardware_interface=hardware_interface,
            planner_client=planner_client,
            planner_transport=planner_transport,
            station_config=station_config,
            robots_config=robots_config,
            scene_runtime=scene_runtime,
        )
        if not setup_result.success:
            print("Board setup FAILED. Aborting assembly.")
            return False

        board_setup_overlay_events = list(setup_result.overlay_events)
        board_setup_duration_s = setup_result.total_duration_s

        if save_snapshot_path:
            home_joints = {
                robot_def.robot_name: list(robot_def.home_joint_angles_rad)
                for robot_def in robots_config.robots
            }
            saveSnapshot(save_snapshot_path, setup_result.overlay_events, home_joints)
            print(f"    Snapshot saved to: {save_snapshot_path}")

    if board_setup_only:
        print("\n[2] Skipping wire routing. Rendering video...")
        _renderVideoLoop(
            scene_runtime=scene_runtime,
            hardware_interface=hardware_interface,
            scene_overlay=scene_overlay,
            total_playback_s=board_setup_duration_s,
            board_setup_events=board_setup_overlay_events,
            wire_routing_events=[],
            output_path=output_path,
            fps=30
        )
        print("\n" + "=" * 60)
        print("Board setup simulation COMPLETE.")
        print("=" * 60)
        return True

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

    route_wire_steps = []
    if wire_routing_phase and wire_routing_phase.steps:
        route_wire_steps = [
            step for step in wire_routing_phase.steps
            if step.process_type == ProcessType.ROUTE_WIRE
        ]

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
        coordinator.notifyAtHome(robot_name, board_setup_duration_s)

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
        wire_color = (0.95, 0.55, 0.1, 1.0)
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

    print("\n[4] Rendering video...")
    _renderVideoLoop(
        scene_runtime=scene_runtime,
        hardware_interface=hardware_interface,
        scene_overlay=scene_overlay,
        total_playback_s=total_time,
        board_setup_events=board_setup_overlay_events,
        wire_routing_events=all_routing_events,
        output_path=output_path,
        fps=30
    )

    print("\n" + "=" * 60)
    print(f"Full assembly COMPLETE: {routed_count}/{len(route_wire_steps)} wires routed.")
    print("=" * 60)

    return failed_count == 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Render full assembly simulation to MP4.",
    )
    parser.add_argument(
        "--cdm-file", type=str, required=True,
        help="Path to CDM wire harness JSON file.",
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to output MP4 video file.",
    )
    parser.add_argument(
        "--load-snapshot", type=str, default=None,
        help="Path to a board-setup snapshot JSON to skip board setup.",
    )
    parser.add_argument(
        "--save-snapshot", type=str, default=None,
        help="Path to save board-setup snapshot JSON after board setup.",
    )
    parser.add_argument(
        "--board-setup-only", action="store_true",
        help="Only run and render the board setup phase.",
    )
    args = parser.parse_args()

    success = runFullAssemblyAndRender(
        cdm_file=args.cdm_file,
        output_path=args.output,
        load_snapshot_path=args.load_snapshot,
        save_snapshot_path=args.save_snapshot,
        board_setup_only=args.board_setup_only,
    )

    os._exit(0 if success else 1)
