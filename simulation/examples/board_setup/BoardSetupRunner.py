"""
High-level board setup orchestration.

Loads CDM, generates layout, builds simulation, pre-plans motions,
and either runs headless or launches the viewer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from simulation.backend.SimulationExecutor import SimulationExecutor
from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.ConfigModels import SceneObjectsConfig
from simulation.core.CoordinateTransform import AxisMapping, BoardToWorldTransform, WorldToRobotBaseTransform
from simulation.core.SceneBuilder import SceneBuilder
from simulation.examples.ViewerSupport import probe_viewer_support
from simulation.examples.board_setup.ViewerPlaybackLoop import runViewerLoop
from simulation.interface.SimulationHardwareAdapter import SimulationHardwareAdapter
from simulation.planning.BoardSetupExecutor import BoardSetupExecutor, BoardSetupResult
from simulation.planning.GraspOrientationPlanner import GraspOrientationPlanner
from simulation.planning.LayoutToSimulationBridge import (
    BoardSetupMotionPlan,
    LayoutResult,
    generateLayout,
    generateMotionPlans,
    loadHarnessFromJson,
)
from simulation.planning.MoveItPlannerClient import PlannerClient
from simulation.planning.OrientationSource import RandomOrientationSource
from simulation.planning.PinocchioCartesianTransport import PinocchioCartesianTransport
from simulation.planning.ReactiveExecutor import ReactiveExecutor
from simulation.planning.TrajectoryCollisionChecker import (
    SharedAreaPolicy,
    TrajectoryCollisionChecker,
)
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator
from simulation.visualization.SceneObjectOverlay import SceneObjectOverlay

logger = logging.getLogger(__name__)


def buildSimulationStack(config_loader: ConfigLoader):
    station_config = config_loader.load_station_config()
    robots_config = config_loader.load_robots_config()
    grippers_config = config_loader.load_grippers_config()

    empty_scene_objects = SceneObjectsConfig(
        peg_catalog={}, peg_instances=[],
        connector_holder_instances=[], connector_plug_instances=[],
    )

    scene_runtime = SceneBuilder(
        station_config=station_config,
        robots_config=robots_config,
        grippers_config=grippers_config,
        scene_objects_config=empty_scene_objects,
    ).build()

    simulation_executor = SimulationExecutor(
        scene_runtime=scene_runtime, control_frequency_hz=125.0,
    )
    hardware_interface = SimulationHardwareAdapter(
        simulation_executor=simulation_executor, command_frequency_hz=125.0,
    )
    planner_transport = PinocchioCartesianTransport()
    planner_client = PlannerClient(planning_transport=planner_transport)

    return scene_runtime, hardware_interface, planner_client, planner_transport, station_config, robots_config


def printPlanSummary(motion_plans: List[BoardSetupMotionPlan]) -> None:
    num_pegs = sum(1 for plan in motion_plans if plan.object_type == "peg")
    num_holders = sum(1 for plan in motion_plans if plan.object_type == "connector_holder")
    left_count = sum(1 for plan in motion_plans if plan.robot_name == "left")
    right_count = sum(1 for plan in motion_plans if plan.robot_name == "right")

    print(f"  Total objects: {len(motion_plans)} ({num_pegs} pegs, {num_holders} holders)")
    print(f"  Robot assignments: left={left_count}, right={right_count}")

    for plan in motion_plans:
        world_pos = plan.placement_world_m
        robot_pos = plan.placement_pose.position_m
        print(
            f"    {plan.object_type:20s} {plan.object_id:12s} -> "
            f"world=({world_pos[0]:+.3f}, {world_pos[1]:+.3f}, {world_pos[2]:.3f}) "
            f"robot=({robot_pos[0]:+.3f}, {robot_pos[1]:+.3f}, {robot_pos[2]:.3f}) "
            f"[{plan.robot_name}]"
        )


def runBoardSetup(
    cdm_file: str,
    use_viewer: bool = False,
    force_viewer: bool = False,
    keep_open: bool = False,
    use_reactive: bool = False,
    step_headless: bool = True,
    hardware_interface: RobotHardwareInterface | None = None,
    planner_client: PlannerClient | None = None,
    planner_transport: PinocchioCartesianTransport | None = None,
    station_config: StationConfig | None = None,
    robots_config: RobotsConfig | None = None,
    scene_runtime: SceneRuntime | None = None,
) -> BoardSetupResult:
    """End-to-end board setup execution."""
    print("=" * 60)
    print("Board Setup Simulation")
    print("=" * 60)

    print(f"\n[1] Loading CDM from: {cdm_file}")
    harness = loadHarnessFromJson(cdm_file)
    print(f"    Harness: {harness.id} ({harness.part_number})")

    simulation_root_path = Path(__file__).resolve().parent.parent.parent
    config_loader = ConfigLoader(str(simulation_root_path))

    print("\n[2] Loading board setup config...")
    board_setup_config = config_loader.load_board_setup_config()

    print("\n[3] Generating board layout...")
    layout_result = generateLayout(
        harness,
        cdm_file_path=cdm_file,
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
    )
    print(f"    Layout board: {layout_result.board_width_mm:.0f} x {layout_result.board_height_mm:.0f} mm")

    print("\n[4] Building simulation stack...")
    if hardware_interface is None:
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

    print("\n[5] Generating motion plans...")
    motion_plans = generateMotionPlans(
        harness=harness,
        layout_result=layout_result,
        board_setup_config=board_setup_config,
        board_transform=board_transform,
        robot_definitions=robots_config.robots,
    )
    printPlanSummary(motion_plans)

    print("\n[6] Pre-planning and queuing all setpoints (parallel)...")
    robot_base_positions = {
        robot_def.robot_name: tuple(robot_def.base_position_m)
        for robot_def in robots_config.robots
    }
    trajectory_store = TrajectoryStore()
    workspace_coordinator = WorkspaceCoordinator(
        robot_names=[r.robot_name for r in robots_config.robots],
        robot_base_positions=robot_base_positions,
        pickup_clearance_radius_m=board_setup_config.pickup_clearance_radius_m,
        trajectory_store=trajectory_store,
    )
    home_joint_angles_by_robot = {
        robot_def.robot_name: list(robot_def.home_joint_angles_rad)
        for robot_def in robots_config.robots
    }
    robot_base_transforms = {
        robot_def.robot_name: WorldToRobotBaseTransform.fromRobotDefinition(robot_def)
        for robot_def in robots_config.robots
    }
    collision_checker = TrajectoryCollisionChecker(
        fk_solver=planner_transport,
        base_transforms=robot_base_transforms,
    )
    shared_area_policy = SharedAreaPolicy()
    executor = BoardSetupExecutor(
        hardware_interface=hardware_interface,
        planner_client=planner_client,
        workspace_coordinator=workspace_coordinator,
        robot_base_transforms=robot_base_transforms,
        home_joint_angles_by_robot=home_joint_angles_by_robot,
        trajectory_collision_checker=collision_checker,
        shared_area_policy=shared_area_policy,
        board_setup_config=board_setup_config,
    )
    setup_result: BoardSetupResult
    if use_reactive:
        orientation_source = RandomOrientationSource(
            seed=board_setup_config.random_orientation_seed + 1000,
        )
        reactive_executor = ReactiveExecutor(
            step_executor=executor,
            orientation_source=orientation_source,
            robot_base_transforms=robot_base_transforms,
            grasp_planner=GraspOrientationPlanner(
                orientation_source=orientation_source,
                seed=board_setup_config.random_orientation_seed + 1000,
            ),
        )

        last_joint_target = {
            robot_name: executor.getHomeJointAngles(robot_name)
            for robot_name in hardware_interface.robot_names
        }
        for robot_name in hardware_interface.robot_names:
            workspace_coordinator.notifyAtHome(robot_name, 0.0)
        overlay_events = []
        completed_steps = 0
        for plan_index, motion_plan in enumerate(motion_plans, start=1):
            step_label = f"[{plan_index}/{len(motion_plans)}]"
            step_result = reactive_executor.executeNextStep(
                motion_plan=motion_plan,
                last_joint_target=last_joint_target,
                overlay_events=overlay_events,
                step_label=step_label,
            )
            if not step_result.success:
                total_duration_s = max(
                    workspace_coordinator.getRobotState(robot_name).current_time_s
                    for robot_name in hardware_interface.robot_names
                )
                setup_result = BoardSetupResult(
                    success=False,
                    completed_steps=completed_steps,
                    total_steps=len(motion_plans),
                    total_duration_s=total_duration_s,
                    overlay_events=overlay_events,
                    failed_step_id=motion_plan.step_id,
                    failure_message=step_result.error_message,
                )
                break
            completed_steps += 1
        else:
            total_duration_s = max(
                workspace_coordinator.getRobotState(robot_name).current_time_s
                for robot_name in hardware_interface.robot_names
            )
            setup_result = BoardSetupResult(
                success=True,
                completed_steps=completed_steps,
                total_steps=len(motion_plans),
                total_duration_s=total_duration_s,
                overlay_events=overlay_events,
            )
    else:
        setup_result = executor.prequeuePlans(motion_plans)
    scene_overlay = SceneObjectOverlay()

    if not setup_result.success:
        print(f"\nPre-planning FAILED at step {setup_result.failed_step_id}: "
              f"{setup_result.failure_message}")
        return setup_result

    print(f"    Sequence ready: {setup_result.total_duration_s:.1f} s total")

    if not use_viewer:
        if step_headless:
            print("\n[7] Running headless...")
            hardware_interface.stepToTimestamp(setup_result.total_duration_s)
        else:
            print("\n[7] Plans queued, skipping headless step for external rendering...")
    else:
        is_supported, reason_message = probe_viewer_support()
        if not is_supported and not force_viewer:
            print(f"Viewer disabled: {reason_message}")
            hardware_interface.stepToTimestamp(setup_result.total_duration_s)
        else:
            print("\n[7] Launching viewer...")
            runViewerLoop(
                scene_runtime, hardware_interface,
                scene_overlay, setup_result, keep_open,
            )

    print("\n" + "=" * 60)
    print(f"Board setup COMPLETE: {setup_result.completed_steps}/{setup_result.total_steps} objects placed.")
    print("=" * 60)

    return setup_result
