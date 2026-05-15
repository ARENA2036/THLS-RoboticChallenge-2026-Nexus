"""
Collect detailed pipeline statistics for both harness variants.

Measures wall-clock time for each pipeline stage and extracts per-step
sim-time breakdowns from the overlay event log.

Run from project root:
    python simulation/examples/collect_statistics.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.examples.board_setup.BoardSetupRunner import buildSimulationStack, printPlanSummary
from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.CoordinateTransform import AxisMapping, BoardToWorldTransform, WorldToRobotBaseTransform
from simulation.planning.BoardSetupExecutor import BoardSetupExecutor, OverlayEventType
from simulation.planning.LayoutToSimulationBridge import generateLayout, generateMotionPlans, loadHarnessFromJson
from simulation.planning.TrajectoryCollisionChecker import SharedAreaPolicy, TrajectoryCollisionChecker
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator
from layout_generator.LayoutModels import PegPlacementReason


CDM_FILES = {
    "medium":  str(PROJECT_ROOT / "public" / "cdm" / "examples" / "medium_harness.json"),
    "complex": str(PROJECT_ROOT / "public" / "cdm" / "examples" / "complex_harness.json"),
}

all_stats = {}

for variant_name, cdm_file in CDM_FILES.items():
    print(f"\n{'='*60}")
    print(f"  {variant_name}")
    print(f"{'='*60}")

    stats = {}

    # ── Stage 1: CDM load ────────────────────────────────────────────────────
    t0 = time.perf_counter()
    harness = loadHarnessFromJson(cdm_file)
    stats["t_cdm_load_ms"] = (time.perf_counter() - t0) * 1000

    # ── Stage 2: Layout generation ───────────────────────────────────────────
    simulation_root = Path(__file__).resolve().parents[1]
    config_loader = ConfigLoader(str(simulation_root))
    board_setup_config = config_loader.load_board_setup_config()

    t0 = time.perf_counter()
    layout_result = generateLayout(
        harness, cdm_file_path=cdm_file,
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
    )
    stats["t_layout_ms"] = (time.perf_counter() - t0) * 1000
    stats["board_w_mm"] = layout_result.board_width_mm
    stats["board_h_mm"] = layout_result.board_height_mm

    # ── Stage 3: Simulation stack build ─────────────────────────────────────
    t0 = time.perf_counter()
    (scene_runtime, hardware_interface, planner_client,
     planner_transport, station_config, robots_config) = buildSimulationStack(config_loader)
    stats["t_scene_build_ms"] = (time.perf_counter() - t0) * 1000

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

    # ── Stage 4: Motion plan generation ─────────────────────────────────────
    t0 = time.perf_counter()
    motion_plans = generateMotionPlans(
        harness=harness, layout_result=layout_result,
        board_setup_config=board_setup_config, board_transform=board_transform,
        robot_definitions=robots_config.robots,
    )
    stats["t_motion_gen_ms"] = (time.perf_counter() - t0) * 1000
    stats["n_motions"] = len(motion_plans)
    stats["n_pegs"] = sum(1 for p in motion_plans if p.object_type == "peg")
    stats["n_holders"] = sum(1 for p in motion_plans if p.object_type == "connector_holder")
    stats["n_left"] = sum(1 for p in motion_plans if p.robot_name == "left")
    stats["n_right"] = sum(1 for p in motion_plans if p.robot_name == "right")

    # ── Stage 5: IK pre-planning ─────────────────────────────────────────────
    robot_base_positions = {r.robot_name: tuple(r.base_position_m) for r in robots_config.robots}
    trajectory_store = TrajectoryStore()
    workspace_coordinator = WorkspaceCoordinator(
        robot_names=[r.robot_name for r in robots_config.robots],
        robot_base_positions=robot_base_positions,
        pickup_clearance_radius_m=board_setup_config.pickup_clearance_radius_m,
        trajectory_store=trajectory_store,
    )
    home_joints = {r.robot_name: list(r.home_joint_angles_rad) for r in robots_config.robots}
    robot_base_transforms = {
        r.robot_name: WorldToRobotBaseTransform.fromRobotDefinition(r)
        for r in robots_config.robots
    }
    collision_checker = TrajectoryCollisionChecker(
        fk_solver=planner_transport, base_transforms=robot_base_transforms,
    )
    executor = BoardSetupExecutor(
        hardware_interface=hardware_interface, planner_client=planner_client,
        workspace_coordinator=workspace_coordinator,
        robot_base_transforms=robot_base_transforms,
        home_joint_angles_by_robot=home_joints,
        trajectory_collision_checker=collision_checker,
        shared_area_policy=SharedAreaPolicy(),
        board_setup_config=board_setup_config,
    )

    t0 = time.perf_counter()
    setup_result = executor.prequeuePlans(motion_plans)
    stats["t_ik_planning_ms"] = (time.perf_counter() - t0) * 1000
    stats["sim_total_s"] = setup_result.total_duration_s

    # ── Stage 6: Analyse overlay events for per-step timing ─────────────────
    events = setup_result.overlay_events

    # Pair ADD_CARRIED → PLACE_OBJECT per object_id to get per-step durations
    add_times = {}
    place_times = {}
    for ev in events:
        if ev.event_type == OverlayEventType.ADD_CARRIED:
            add_times[ev.object_id] = (ev.timestamp_s, ev.object_type, ev.robot_name)
        elif ev.event_type == OverlayEventType.PLACE_OBJECT:
            place_times[ev.object_id] = ev.timestamp_s

    step_durations_by_type = defaultdict(list)
    step_durations_by_robot = defaultdict(list)

    for obj_id, (t_add, obj_type, robot) in add_times.items():
        t_place = place_times.get(obj_id)
        if t_place is not None:
            dur = t_place - t_add
            step_durations_by_type[obj_type].append(dur)
            step_durations_by_robot[robot].append(dur)

    for obj_type, durs in step_durations_by_type.items():
        key = f"step_{obj_type}"
        stats[f"{key}_count"] = len(durs)
        stats[f"{key}_mean_s"] = sum(durs) / len(durs) if durs else 0
        stats[f"{key}_min_s"] = min(durs) if durs else 0
        stats[f"{key}_max_s"] = max(durs) if durs else 0

    for robot, durs in step_durations_by_robot.items():
        stats[f"robot_{robot}_steps"] = len(durs)
        stats[f"robot_{robot}_active_s"] = sum(durs)

    # Harness CDM stats
    stats["n_wires"] = len(harness.wires)
    stats["n_connectors"] = len(harness.connector_occurrences)
    stats["n_segments"] = len(harness.segments)
    stats["n_nodes"] = len(harness.nodes)
    stats["total_wire_length_mm"] = int(sum(s.length for s in harness.segments if s.length))

    all_stats[variant_name] = stats

# ── Print full report ─────────────────────────────────────────────────────────
print("\n\n" + "="*70)
print("PIPELINE STATISTICS REPORT")
print("="*70)

for variant, s in all_stats.items():
    print(f"\n── {variant.upper()} HARNESS ─────────────────────────────")
    print(f"  CDM:          {s['n_wires']} wires, {s['n_connectors']} connectors, "
          f"{s['n_segments']} segments, {s['n_nodes']} nodes, "
          f"{s['total_wire_length_mm']} mm total length")
    print(f"  Board:        {s['board_w_mm']:.0f} × {s['board_h_mm']:.0f} mm")
    print()
    print(f"  Wall-clock pipeline timings:")
    print(f"    CDM load:        {s['t_cdm_load_ms']:.1f} ms")
    print(f"    Layout gen:      {s['t_layout_ms']:.1f} ms")
    print(f"    Scene build:     {s['t_scene_build_ms']:.1f} ms")
    print(f"    Motion gen:      {s['t_motion_gen_ms']:.1f} ms")
    print(f"    IK pre-planning: {s['t_ik_planning_ms']:.1f} ms")
    total_pipeline = (s['t_cdm_load_ms'] + s['t_layout_ms'] +
                      s['t_motion_gen_ms'] + s['t_ik_planning_ms'])
    print(f"    → Total (excl. scene): {total_pipeline:.0f} ms")
    print()
    print(f"  Simulation (scheduled time):")
    print(f"    Total:        {s['sim_total_s']:.1f} s")
    print(f"    Motions:      {s['n_motions']} ({s['n_pegs']} pegs, {s['n_holders']} holders)")
    print(f"    Left robot:   {s.get('n_left',0)} motions, "
          f"{s.get('robot_left_active_s',0):.1f} s active")
    print(f"    Right robot:  {s.get('n_right',0)} motions, "
          f"{s.get('robot_right_active_s',0):.1f} s active")
    for obj_type in ["peg", "connector_holder"]:
        k = f"step_{obj_type}"
        if f"{k}_count" in s:
            print(f"    {obj_type:20s}: {s[f'{k}_count']} steps, "
                  f"mean {s[f'{k}_mean_s']:.1f} s, "
                  f"min {s[f'{k}_min_s']:.1f} s, "
                  f"max {s[f'{k}_max_s']:.1f} s")
