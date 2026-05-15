"""
Batch full-simulation pipeline for all 100 synthetic harness variants.

For each CDM this script runs:
  1. Board-setup IK pre-planning  (prequeuePlans, no physics stepping)
  2. Wire-routing IK scheduling   (executeRouteWire, no physics stepping)

and records scheduled execution times together with a parallel / single-arm /
idle breakdown for both phases.

Output
------
  public/cdm/examples/generated/full_simulation_results.csv
  public/cdm/examples/generated/full_simulation_skipped.csv

Run from project root
---------------------
    simulation/venv/bin/python simulation/examples/run_batch_full_simulation.py
"""

from __future__ import annotations

import csv
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPModels import PhaseType, ProcessType, RouteWireParameters
from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.ConfigModels import BoardSetupConfig, ObjectPickupConfig
from simulation.core.CoordinateTransform import (
    AxisMapping,
    BoardToWorldTransform,
    WorldToRobotBaseTransform,
)
from simulation.examples.board_setup.BoardSetupRunner import buildSimulationStack
from simulation.interface.CameraMockService import CameraMockServiceImpl
from simulation.interface.ForceTorqueMockService import ForceTorqueMockServiceImpl
from simulation.planning.BoardSetupExecutor import BoardSetupExecutor
from simulation.planning.LayoutToSimulationBridge import (
    generateLayout,
    generateMotionPlans,
    loadHarnessFromJson,
)
from simulation.planning.MotionSequenceBuilder import MotionSequenceBuilder
from simulation.planning.TrajectoryCollisionChecker import (
    SharedAreaPolicy,
    TrajectoryCollisionChecker,
)
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WireRoutingExecutor import WireRoutingExecutor
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator

# ── Paths ─────────────────────────────────────────────────────────────────────
GENERATED_DIR = PROJECT_ROOT / "public" / "cdm" / "examples" / "generated"
MANIFEST_PATH = GENERATED_DIR / "manifest.csv"
OUTPUT_RESULTS = GENERATED_DIR / "full_simulation_results.csv"
OUTPUT_SKIPPED = GENERATED_DIR / "full_simulation_skipped.csv"

# ── Supply tray grid (identical to run_batch_evaluation.py) ───────────────────
_TRAY_X_POSITIONS = [-0.28, -0.20, -0.12, -0.04, 0.04, 0.12, 0.20, 0.28]
_TRAY_Y_ROWS = [-0.35, -0.43, -0.51, -0.59]
_TRAY_Z = 0.75
_MAX_TRAY_SLOTS = len(_TRAY_X_POSITIONS) * len(_TRAY_Y_ROWS)

RESULTS_FIELDS = [
    "harness_id", "tier", "topology",
    "n_connectors", "n_wires",
    # Board setup
    "board_setup_duration_s",
    "board_parallel_s", "board_single_s", "board_idle_s",
    # Wire routing
    "wire_routing_duration_s",
    "routing_parallel_s", "routing_single_s", "routing_idle_s",
    # Combined
    "total_duration_s",
    "total_parallel_pct", "total_single_pct", "total_idle_pct",
    # Routing quality
    "wires_routed", "wires_failed",
]

SKIPPED_FIELDS = [
    "harness_id", "tier", "topology", "n_connectors", "n_wires", "reason",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_tray_position(slot_index: int) -> Tuple[float, float, float]:
    col = slot_index % len(_TRAY_X_POSITIONS)
    row = min(slot_index // len(_TRAY_X_POSITIONS), len(_TRAY_Y_ROWS) - 1)
    return (_TRAY_X_POSITIONS[col], _TRAY_Y_ROWS[row], _TRAY_Z)


def _patch_pickup_config(
    base_config: BoardSetupConfig,
    extra_ids: List[Tuple[str, str]],
) -> BoardSetupConfig:
    existing_ids = {p.object_id for p in base_config.pickup_positions}
    new_pickups = list(base_config.pickup_positions)
    slot_index = 0
    for object_id, object_type in extra_ids:
        if object_id in existing_ids:
            continue
        pos = _build_tray_position(slot_index % _MAX_TRAY_SLOTS)
        new_pickups.append(
            ObjectPickupConfig(
                object_id=object_id,
                object_type=object_type,
                pickup_position_m=pos,
            )
        )
        existing_ids.add(object_id)
        slot_index += 1
    data = base_config.model_dump()
    data["pickup_positions"] = [p.model_dump() for p in new_pickups]
    return BoardSetupConfig.model_validate(data)


def _clear_hardware_queue(hardware_interface) -> None:
    """Discard accumulated timed setpoints between CDM runs.

    prequeuePlans / executeRouteWire queue setpoints into the MuJoCo
    executor for later physics playback.  Since we never call
    stepToTimestamp in batch mode, the queue only grows.  Clearing it
    keeps memory bounded without affecting IK-planning correctness.
    """
    exec_ = hardware_interface.simulation_executor
    for rn in hardware_interface.robot_names:
        state = exec_.robot_command_states.get(rn)
        if state is not None:
            state.queued_setpoints.clear()


def _compute_timing_from_intervals(
    intervals: List[Tuple[str, float, float]],
    robot_names: List[str],
    total_duration_s: float,
) -> Tuple[float, float, float]:
    """Return (parallel_s, single_s, idle_s) from a list of (robot, start, end) tuples."""

    by_robot: Dict[str, List[Tuple[float, float]]] = {rn: [] for rn in robot_names}
    for rn, s, e in intervals:
        if rn in by_robot and e > s:
            by_robot[rn].append((s, e))

    def merge(ivs: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if not ivs:
            return []
        ivs = sorted(ivs)
        merged = [list(ivs[0])]
        for s, e in ivs[1:]:
            if s <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        return [(a, b) for a, b in merged]

    def total_len(ivs: List[Tuple[float, float]]) -> float:
        return sum(e - s for s, e in ivs)

    def intersect(
        a: List[Tuple[float, float]],
        b: List[Tuple[float, float]],
    ) -> List[Tuple[float, float]]:
        res: List[Tuple[float, float]] = []
        i = j = 0
        while i < len(a) and j < len(b):
            lo = max(a[i][0], b[j][0])
            hi = min(a[i][1], b[j][1])
            if lo < hi:
                res.append((lo, hi))
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
        return res

    rns = sorted(robot_names)
    if len(rns) < 2:
        left_m = merge(by_robot.get(rns[0], []))
        left_s = total_len(left_m)
        return 0.0, left_s, max(0.0, total_duration_s - left_s)

    left_m = merge(by_robot.get(rns[0], []))
    right_m = merge(by_robot.get(rns[1], []))

    parallel_s = total_len(intersect(left_m, right_m))
    left_active = total_len(left_m)
    right_active = total_len(right_m)
    single_s = left_active + right_active - 2.0 * parallel_s
    idle_s = max(0.0, total_duration_s - parallel_s - single_s)
    return parallel_s, single_s, idle_s


def _intervals_from_trajectory_store(
    trajectory_store: TrajectoryStore,
    robot_names: List[str],
    total_duration_s: float,
) -> List[Tuple[str, float, float]]:
    """Extract (robot_name, start_s, end_s) triples from a TrajectoryStore."""
    big = total_duration_s + 1.0
    result = []
    for rn in robot_names:
        for seg in trajectory_store.getSegmentsInWindow(rn, 0.0, big):
            result.append((rn, seg.start_time_s, seg.end_time_s))
    return result


def _build_peg_positions_world(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, Tuple[float, float, float]]:
    return {
        peg.id: board_transform.transformToWorld(peg.position.x, peg.position.y)
        for peg in layout_response.pegs
    }


def _build_peg_orientations_world(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, float]:
    return {
        peg.id: board_transform.axis_mapping.transformOrientationDeg(
            getattr(peg, "orientation_deg", 0.0)
        )
        for peg in layout_response.pegs
    }


def _build_connector_positions_world(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, Tuple[float, float, float]]:
    return {
        holder.connector_id: board_transform.transformToWorld(
            holder.position.x, holder.position.y
        )
        for holder in layout_response.connector_holders
    }


def _build_connector_orientations_world(
    layout_response,
    board_transform: BoardToWorldTransform,
) -> Dict[str, float]:
    return {
        holder.connector_id: board_transform.axis_mapping.transformOrientationDeg(
            getattr(holder, "orientation_deg", 0.0)
        )
        for holder in layout_response.connector_holders
    }


# ── Per-CDM runner ─────────────────────────────────────────────────────────────

def run_variant(
    harness_id: str,
    cdm_path: Path,
    config_loader: ConfigLoader,
    robots_config,
    station_config,
    board_setup_config: BoardSetupConfig,
    wire_routing_config,
    hardware_interface,
    planner_client,
    planner_transport,
) -> dict | None:
    """
    Run full IK-planning pipeline for one CDM.

    Returns a metrics dict on success, or None if board-setup IK fails.
    Failures in individual wire routing steps are recorded but do not
    cause the whole variant to be skipped.
    """
    # ── CDM + layout ──────────────────────────────────────────────────────────
    harness = loadHarnessFromJson(str(cdm_path))

    layout_result = generateLayout(
        harness,
        cdm_file_path=str(cdm_path),
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
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

    # Patch pickup positions for synthetic connector/peg IDs
    conn_ids = [(occ.id, "connector_holder") for occ in harness.connector_occurrences]
    peg_ids = [(f"peg_{i:04d}", "peg") for i in range(1, 51)]
    patched_config = _patch_pickup_config(board_setup_config, conn_ids + peg_ids)

    # ── BoP generation ────────────────────────────────────────────────────────
    bop_config = BoPGeneratorConfig(
        production_id="sim_full_batch",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_result.response,
                station_id="assembly_station_1",
            )
        ],
    )
    production_bop = BoPGeneratorService().generate(bop_config)

    wire_routing_phase = None
    for phase in production_bop.phases:
        if phase.phase_type == PhaseType.WIRE_ROUTING:
            wire_routing_phase = phase
            break

    route_wire_steps = []
    if wire_routing_phase is not None:
        route_wire_steps = [
            step for step in wire_routing_phase.steps
            if step.process_type == ProcessType.ROUTE_WIRE
        ]

    # ── Motion plan generation ────────────────────────────────────────────────
    motion_plans = generateMotionPlans(
        harness=harness,
        layout_result=layout_result,
        board_setup_config=patched_config,
        board_transform=board_transform,
        robot_definitions=robots_config.robots,
    )

    robot_names = sorted(r.robot_name for r in robots_config.robots)
    robot_base_positions = {r.robot_name: tuple(r.base_position_m) for r in robots_config.robots}
    robot_base_transforms = {
        r.robot_name: WorldToRobotBaseTransform.fromRobotDefinition(r)
        for r in robots_config.robots
    }
    home_joints = {r.robot_name: list(r.home_joint_angles_rad) for r in robots_config.robots}

    # ── Phase 1: Board-setup IK planning ──────────────────────────────────────
    trajectory_store = TrajectoryStore()
    coordinator = WorkspaceCoordinator(
        robot_names=robot_names,
        robot_base_positions=robot_base_positions,
        pickup_clearance_radius_m=patched_config.pickup_clearance_radius_m,
        trajectory_store=trajectory_store,
    )
    collision_checker = TrajectoryCollisionChecker(
        fk_solver=planner_transport,
        base_transforms=robot_base_transforms,
    )
    executor = BoardSetupExecutor(
        hardware_interface=hardware_interface,
        planner_client=planner_client,
        workspace_coordinator=coordinator,
        robot_base_transforms=robot_base_transforms,
        home_joint_angles_by_robot=home_joints,
        trajectory_collision_checker=collision_checker,
        shared_area_policy=SharedAreaPolicy(),
        board_setup_config=patched_config,
    )

    setup_result = executor.prequeuePlans(motion_plans)
    if not setup_result.success:
        return None

    board_setup_duration_s = setup_result.total_duration_s

    # Timing breakdown from TrajectoryStore segments
    board_intervals = _intervals_from_trajectory_store(
        trajectory_store, robot_names, board_setup_duration_s
    )
    board_parallel_s, board_single_s, board_idle_s = _compute_timing_from_intervals(
        board_intervals, robot_names, board_setup_duration_s
    )

    # Clear accumulated setpoints before wire routing
    _clear_hardware_queue(hardware_interface)

    # ── Phase 2: Wire-routing IK scheduling ───────────────────────────────────
    wr_coordinator = WorkspaceCoordinator(
        robot_names=robot_names,
        robot_base_positions=robot_base_positions,
        pickup_clearance_radius_m=patched_config.pickup_clearance_radius_m,
    )
    for rn in robot_names:
        wr_coordinator.notifyAtHome(rn, 0.0)

    motion_builders = {
        rn: MotionSequenceBuilder(
            hardware=hardware_interface,
            planner=planner_client,
        )
        for rn in robot_names
    }

    camera_mock = CameraMockServiceImpl()
    force_mock = ForceTorqueMockServiceImpl()

    routing_executor = WireRoutingExecutor(
        motion_builders=motion_builders,
        coordinator=wr_coordinator,
        robot_base_transforms=robot_base_transforms,
        camera_service=camera_mock,
        force_torque_service=force_mock,
        wire_routing_config=wire_routing_config,
        home_joint_angles_by_robot=home_joints,
        robot_base_positions=robot_base_positions,
    )

    peg_positions_world = _build_peg_positions_world(layout_result.response, board_transform)
    peg_orientations_world = _build_peg_orientations_world(layout_result.response, board_transform)
    connector_positions_world = _build_connector_positions_world(layout_result.response, board_transform)
    connector_orientations_world = _build_connector_orientations_world(layout_result.response, board_transform)
    board_surface_z = board_transform.getBoardSurfaceZ()

    routing_intervals: List[Tuple[str, float, float]] = []
    wires_routed = 0
    wires_failed = 0

    for step in route_wire_steps:
        route_params: RouteWireParameters = step.parameters

        # Snapshot coordinator times before this wire
        t_before = {rn: wr_coordinator.getRobotState(rn).current_time_s for rn in robot_names}

        result = routing_executor.executeRouteWire(
            wire_occurrence_id=route_params.wire_occurrence_id,
            connection_id=route_params.connection_id,
            ordered_peg_ids=route_params.ordered_peg_ids,
            peg_positions_world=peg_positions_world,
            peg_orientations_world=peg_orientations_world,
            extremity_connector_ids=[
                ext.connector_occurrence_id for ext in route_params.extremities
            ],
            connector_positions_world=connector_positions_world,
            connector_orientations_world=connector_orientations_world,
            wire_color_rgba=(0.95, 0.55, 0.1, 1.0),
            wire_cross_section_mm2=0.5,
            board_surface_z=board_surface_z,
        )

        # Snapshot coordinator times after this wire
        t_after = {rn: wr_coordinator.getRobotState(rn).current_time_s for rn in robot_names}

        # Record active intervals for robots whose time advanced
        for rn in robot_names:
            if t_after[rn] > t_before[rn] + 1e-9:
                routing_intervals.append((rn, t_before[rn], t_after[rn]))

        if result.success:
            wires_routed += 1
        else:
            wires_failed += 1

        force_mock.resetRamp()

        # Clear accumulated setpoints after each wire to keep memory bounded
        _clear_hardware_queue(hardware_interface)

    wire_routing_duration_s = max(
        wr_coordinator.getRobotState(rn).current_time_s for rn in robot_names
    )

    routing_parallel_s, routing_single_s, routing_idle_s = _compute_timing_from_intervals(
        routing_intervals, robot_names, wire_routing_duration_s
    )

    total_duration_s = board_setup_duration_s + wire_routing_duration_s
    total_parallel_s = board_parallel_s + routing_parallel_s
    total_single_s = board_single_s + routing_single_s
    total_idle_s = board_idle_s + routing_idle_s

    if total_duration_s > 1e-9:
        total_parallel_pct = round(100.0 * total_parallel_s / total_duration_s, 1)
        total_single_pct = round(100.0 * total_single_s / total_duration_s, 1)
        total_idle_pct = round(100.0 * total_idle_s / total_duration_s, 1)
    else:
        total_parallel_pct = total_single_pct = total_idle_pct = 0.0

    return {
        "board_setup_duration_s": round(board_setup_duration_s, 2),
        "board_parallel_s": round(board_parallel_s, 2),
        "board_single_s": round(board_single_s, 2),
        "board_idle_s": round(board_idle_s, 2),
        "wire_routing_duration_s": round(wire_routing_duration_s, 2),
        "routing_parallel_s": round(routing_parallel_s, 2),
        "routing_single_s": round(routing_single_s, 2),
        "routing_idle_s": round(routing_idle_s, 2),
        "total_duration_s": round(total_duration_s, 2),
        "total_parallel_pct": total_parallel_pct,
        "total_single_pct": total_single_pct,
        "total_idle_pct": total_idle_pct,
        "wires_routed": wires_routed,
        "wires_failed": wires_failed,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def load_manifest() -> list[dict]:
    rows = []
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def main() -> None:
    manifest = load_manifest()
    print(f"Loaded manifest: {len(manifest)} harnesses")

    # Build simulation stack once — expensive (MuJoCo + Pinocchio)
    simulation_root = Path(__file__).resolve().parents[1]
    config_loader = ConfigLoader(str(simulation_root))
    board_setup_config = config_loader.load_board_setup_config()
    wire_routing_config = config_loader.load_wire_routing_config()

    (
        scene_runtime, hardware_interface, planner_client,
        planner_transport, station_config, robots_config,
    ) = buildSimulationStack(config_loader)

    results = []
    skipped = []
    total = len(manifest)

    t_wall_start = time.perf_counter()

    with (
        OUTPUT_RESULTS.open("w", newline="", encoding="utf-8") as f_results,
        OUTPUT_SKIPPED.open("w", newline="", encoding="utf-8") as f_skipped,
    ):
        writer_results = csv.DictWriter(f_results, fieldnames=RESULTS_FIELDS)
        writer_skipped = csv.DictWriter(f_skipped, fieldnames=SKIPPED_FIELDS)
        writer_results.writeheader()
        writer_skipped.writeheader()

        for i, row in enumerate(manifest):
            harness_id = row["harness_id"]
            tier = row["tier"]
            topology = row["topology"]
            cdm_path = GENERATED_DIR / f"{harness_id}.json"

            elapsed = time.perf_counter() - t_wall_start
            print(
                f"[{i+1:3d}/{total}] {harness_id} ({tier:8s} {topology:10s}) "
                f"{row['n_connectors']:3s}C {row['n_wires']:4s}W  "
                f"[{elapsed/60:.1f} min elapsed]...",
                end=" ",
                flush=True,
            )

            try:
                metrics = run_variant(
                    harness_id=harness_id,
                    cdm_path=cdm_path,
                    config_loader=config_loader,
                    robots_config=robots_config,
                    station_config=station_config,
                    board_setup_config=board_setup_config,
                    wire_routing_config=wire_routing_config,
                    hardware_interface=hardware_interface,
                    planner_client=planner_client,
                    planner_transport=planner_transport,
                )

                if metrics is None:
                    reason = "Board-setup IK pre-planning failed"
                    print(f"SKIP ({reason})")
                    writer_skipped.writerow({
                        "harness_id": harness_id, "tier": tier, "topology": topology,
                        "n_connectors": row["n_connectors"], "n_wires": row["n_wires"],
                        "reason": reason,
                    })
                    f_skipped.flush()
                    skipped.append(harness_id)
                else:
                    print(
                        f"OK  board={metrics['board_setup_duration_s']:.1f}s  "
                        f"routing={metrics['wire_routing_duration_s']:.1f}s  "
                        f"par={metrics['total_parallel_pct']:.0f}%  "
                        f"single={metrics['total_single_pct']:.0f}%  "
                        f"idle={metrics['total_idle_pct']:.0f}%  "
                        f"({metrics['wires_routed']}/{metrics['wires_routed'] + metrics['wires_failed']} wires)"
                    )
                    result_row = {
                        "harness_id": harness_id,
                        "tier": tier,
                        "topology": topology,
                        "n_connectors": row["n_connectors"],
                        "n_wires": row["n_wires"],
                        **metrics,
                    }
                    writer_results.writerow(result_row)
                    f_results.flush()
                    results.append(result_row)

            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                print(f"ERROR: {reason}")
                writer_skipped.writerow({
                    "harness_id": harness_id, "tier": tier, "topology": topology,
                    "n_connectors": row["n_connectors"], "n_wires": row["n_wires"],
                    "reason": reason,
                })
                f_skipped.flush()
                skipped.append(harness_id)
                traceback.print_exc()

    elapsed_total = time.perf_counter() - t_wall_start
    print(f"\n── Summary ──────────────────────────────────────────────────────")
    print(f"  Feasible : {len(results)}/{total}")
    print(f"  Skipped  : {len(skipped)}/{total}")
    print(f"  Wall time: {elapsed_total/60:.1f} min")

    if results:
        def _stat(vals):
            s = sorted(vals)
            return s[0], s[len(s)//2], s[-1]

        board_times = [float(r["board_setup_duration_s"]) for r in results]
        route_times = [float(r["wire_routing_duration_s"]) for r in results]
        par_pcts = [float(r["total_parallel_pct"]) for r in results]

        b_min, b_med, b_max = _stat(board_times)
        r_min, r_med, r_max = _stat(route_times)
        print(f"\n  Board setup (s):   min={b_min:.1f}  median={b_med:.1f}  max={b_max:.1f}")
        print(f"  Wire routing (s):  min={r_min:.1f}  median={r_med:.1f}  max={r_max:.1f}")
        p_min, p_med, p_max = _stat(par_pcts)
        print(f"  Parallel (%):      min={p_min:.0f}  median={p_med:.0f}  max={p_max:.0f}")

    print(f"\n  Results → {OUTPUT_RESULTS}")
    print(f"  Skipped → {OUTPUT_SKIPPED}")


if __name__ == "__main__":
    main()
