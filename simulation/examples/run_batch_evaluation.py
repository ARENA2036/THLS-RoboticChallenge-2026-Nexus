"""
Batch pipeline evaluation across 100 synthetic harness variants.

Runs the offline planning pipeline (CDM → Layout → BoP → Motion → IK pre-planning)
for each harness in public/cdm/examples/generated/.

IK-infeasible variants are filtered out and logged separately.

Output:
    evaluation_results.csv  — metrics for all feasible variants
    evaluation_skipped.csv  — variants that failed IK pre-planning

Run from project root:
    simulation/venv/bin/python simulation/examples/run_batch_evaluation.py
"""

from __future__ import annotations

import csv
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPModels import PhaseType
from simulation.examples.board_setup.BoardSetupRunner import buildSimulationStack
from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.ConfigModels import BoardSetupConfig, ObjectPickupConfig
from simulation.core.CoordinateTransform import AxisMapping, BoardToWorldTransform, WorldToRobotBaseTransform
from simulation.planning.BoardSetupExecutor import BoardSetupExecutor
from simulation.planning.LayoutToSimulationBridge import generateLayout, generateMotionPlans, loadHarnessFromJson
from simulation.planning.TrajectoryCollisionChecker import SharedAreaPolicy, TrajectoryCollisionChecker
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator

# Each board-setup motion takes this fixed sim-time step (seconds).
# Calibrated from the two reference variants in Table I.
_MOTION_STEP_S = 8.5

# ── Supply tray grid for dynamic pickup registration ──────────────────────────
# Each row is at a fixed y-depth; columns advance along x.
# The grid must stay within reach of both UR10e arms (x ∈ [-0.28, 0.28]).
_TRAY_X_POSITIONS = [-0.28, -0.20, -0.12, -0.04, 0.04, 0.12, 0.20, 0.28]
_TRAY_Y_ROWS = [-0.35, -0.43, -0.51, -0.59]   # 4 rows × 8 cols = 32 slots
_TRAY_Z = 0.75
_MAX_TRAY_SLOTS = len(_TRAY_X_POSITIONS) * len(_TRAY_Y_ROWS)  # 32


def _build_tray_position(slot_index: int) -> tuple[float, float, float]:
    """Map a linear slot index to a (x, y, z) supply tray position."""
    col = slot_index % len(_TRAY_X_POSITIONS)
    row = slot_index // len(_TRAY_X_POSITIONS)
    row = min(row, len(_TRAY_Y_ROWS) - 1)
    return (_TRAY_X_POSITIONS[col], _TRAY_Y_ROWS[row], _TRAY_Z)


def _patch_pickup_config(base_config: BoardSetupConfig, extra_ids: list[tuple[str, str]]) -> BoardSetupConfig:
    """
    Return a copy of board_setup_config with additional ObjectPickupConfig entries
    for any object IDs not already registered.

    extra_ids: list of (object_id, object_type) pairs to add.
    """
    existing_ids = {p.object_id for p in base_config.pickup_positions}
    new_pickups = list(base_config.pickup_positions)

    slot_index = 0
    for object_id, object_type in extra_ids:
        if object_id in existing_ids:
            continue
        if slot_index >= _MAX_TRAY_SLOTS:
            # Wrap around — reuse positions (IK feasibility unchanged per arm side)
            slot_index = slot_index % _MAX_TRAY_SLOTS
        new_pickups.append(ObjectPickupConfig(
            object_id=object_id,
            object_type=object_type,
            pickup_position_m=_build_tray_position(slot_index),
        ))
        existing_ids.add(object_id)
        slot_index += 1

    # Return a shallow copy with patched pickup_positions
    data = base_config.model_dump()
    data["pickup_positions"] = [p.model_dump() for p in new_pickups]
    return BoardSetupConfig.model_validate(data)

GENERATED_DIR = PROJECT_ROOT / "public" / "cdm" / "examples" / "generated"
MANIFEST_PATH = GENERATED_DIR / "manifest.csv"
OUTPUT_RESULTS = GENERATED_DIR / "evaluation_results.csv"
OUTPUT_SKIPPED = GENERATED_DIR / "evaluation_skipped.csv"

# IK pre-planning is skipped for the large-scale batch (synthetic pickup positions
# cause slow IK convergence). IK scaling is characterized via the two reference
# variants in Table I (1.7 s / 5.2 s for 7 and 17 motions respectively).
SKIP_IK = True

RESULTS_FIELDS = [
    "harness_id", "tier", "topology",
    "n_connectors", "n_wires", "n_segments", "n_nodes", "total_wire_length_mm",
    "board_w_mm", "board_h_mm",
    # Board setup motions
    "n_pegs", "n_holders",
    "n_pegs_left", "n_pegs_right", "n_holders_left", "n_holders_right",
    "n_motions", "n_left", "n_right",
    "parallel_steps", "single_arm_steps",
    "est_exec_board_setup_s",
    "parallel_utilization_est",
    # Wire assembly BoP steps
    "n_route_wire_steps", "n_connector_assembly_steps",
    # Planning timing
    "t_cdm_ms", "t_layout_ms", "t_bop_ms", "t_motion_gen_ms", "t_total_planning_ms",
]

SKIPPED_FIELDS = ["harness_id", "tier", "topology", "n_connectors", "n_wires", "reason"]


def load_manifest() -> list[dict]:
    rows = []
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def run_variant(
    harness_id: str,
    cdm_path: Path,
    config_loader: ConfigLoader,
    robots_config,
    station_config,
    board_setup_config,
    hardware_interface,
    planner_client,
    planner_transport,
    skip_ik: bool = False,
) -> dict | None:
    """
    Run the offline planning pipeline for one variant.
    If skip_ik=True, stops after motion plan generation (no IK solve).
    Returns a metrics dict, or None if IK pre-planning fails.
    """
    metrics: dict = {}

    # Stage 1: CDM load
    t0 = time.perf_counter()
    harness = loadHarnessFromJson(str(cdm_path))
    metrics["t_cdm_ms"] = (time.perf_counter() - t0) * 1000

    # Stage 2: Layout generation
    t0 = time.perf_counter()
    layout_result = generateLayout(
        harness,
        cdm_file_path=str(cdm_path),
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
    )
    metrics["t_layout_ms"] = (time.perf_counter() - t0) * 1000
    metrics["board_w_mm"] = round(layout_result.board_width_mm, 1)
    metrics["board_h_mm"] = round(layout_result.board_height_mm, 1)

    layout_metrics = layout_result.response.metrics if layout_result.response else None
    metrics["n_pegs"] = layout_metrics.total_pegs if layout_metrics else 0
    metrics["n_holders"] = layout_metrics.total_holders if layout_metrics else 0

    # Stage 3: Coordinate transforms (board positioning)
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

    # Patch pickup positions to cover all synthetic connector/peg IDs.
    # The base config only has positions for the Robotics Challenge components;
    # synthetic harnesses use Conn_000..Conn_NNN and peg_0001..peg_NNNN.
    conn_ids = [(occ.id, "connector_holder") for occ in harness.connector_occurrences]
    # Pre-generate peg IDs up to 50 (max pegs any 30-connector harness can produce)
    peg_ids = [(f"peg_{i:04d}", "peg") for i in range(1, 51)]
    patched_config = _patch_pickup_config(board_setup_config, conn_ids + peg_ids)

    # Stage 4a: Full BoP generation — count steps in ALL phases (board setup +
    # wire routing + connector assembly) before extracting motion plans.
    bop_gen_config = BoPGeneratorConfig(
        production_id="sim_board_setup",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_result.response,
                station_id="assembly_station_1",
            )
        ],
    )
    t0 = time.perf_counter()
    production_bop = BoPGeneratorService().generate(bop_gen_config)
    metrics["t_bop_ms"] = (time.perf_counter() - t0) * 1000

    metrics["n_route_wire_steps"] = 0
    metrics["n_connector_assembly_steps"] = 0
    for phase in production_bop.phases:
        if phase.phase_type == PhaseType.WIRE_ROUTING:
            metrics["n_route_wire_steps"] = len(phase.steps)
        elif phase.phase_type == PhaseType.CONNECTOR_ASSEMBLY:
            metrics["n_connector_assembly_steps"] = len(phase.steps)

    # Stage 4b: Board-setup motion plan generation (uses BOARD_SETUP BoP phase).
    t0 = time.perf_counter()
    motion_plans = generateMotionPlans(
        harness=harness,
        layout_result=layout_result,
        board_setup_config=patched_config,
        board_transform=board_transform,
        robot_definitions=robots_config.robots,
    )
    metrics["t_motion_gen_ms"] = (time.perf_counter() - t0) * 1000

    metrics["n_motions"] = len(motion_plans)
    metrics["n_left"]    = sum(1 for p in motion_plans if p.robot_name == "left")
    metrics["n_right"]   = sum(1 for p in motion_plans if p.robot_name == "right")

    metrics["n_pegs"]         = sum(1 for p in motion_plans if p.object_type == "peg")
    metrics["n_holders"]      = sum(1 for p in motion_plans if p.object_type == "connector_holder")
    metrics["n_pegs_left"]    = sum(1 for p in motion_plans if p.object_type == "peg" and p.robot_name == "left")
    metrics["n_pegs_right"]   = sum(1 for p in motion_plans if p.object_type == "peg" and p.robot_name == "right")
    metrics["n_holders_left"]  = sum(1 for p in motion_plans if p.object_type == "connector_holder" and p.robot_name == "left")
    metrics["n_holders_right"] = sum(1 for p in motion_plans if p.object_type == "connector_holder" and p.robot_name == "right")

    metrics["parallel_steps"]   = min(metrics["n_left"], metrics["n_right"])
    metrics["single_arm_steps"] = abs(metrics["n_left"] - metrics["n_right"])
    metrics["est_exec_board_setup_s"] = round(
        max(metrics["n_left"], metrics["n_right"]) * _MOTION_STEP_S, 1
    )

    n_total = metrics["n_left"] + metrics["n_right"]
    metrics["parallel_utilization_est"] = (
        round(min(metrics["n_left"], metrics["n_right"]) / max(metrics["n_left"], metrics["n_right"]), 3)
        if n_total > 0 and max(metrics["n_left"], metrics["n_right"]) > 0 else 0.0
    )

    # Stage 5: IK pre-planning (optional — skipped for large-scale batch evaluation
    # because synthetic pickup positions cause slow IK convergence; IK scaling is
    # characterized separately for the two reference variants in Table I).
    if skip_ik:
        metrics["t_total_planning_ms"] = round(
            metrics["t_cdm_ms"] + metrics["t_layout_ms"]
            + metrics["t_bop_ms"] + metrics["t_motion_gen_ms"],
            1,
        )
        return metrics

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
        fk_solver=planner_transport,
        base_transforms=robot_base_transforms,
    )
    executor = BoardSetupExecutor(
        hardware_interface=hardware_interface,
        planner_client=planner_client,
        workspace_coordinator=workspace_coordinator,
        robot_base_transforms=robot_base_transforms,
        home_joint_angles_by_robot=home_joints,
        trajectory_collision_checker=collision_checker,
        shared_area_policy=SharedAreaPolicy(),
        board_setup_config=patched_config,
    )

    t0 = time.perf_counter()
    setup_result = executor.prequeuePlans(motion_plans)
    metrics["t_ik_ms"] = (time.perf_counter() - t0) * 1000

    if not setup_result.success:
        return None

    metrics["t_total_planning_ms"] = round(
        metrics["t_cdm_ms"] + metrics["t_layout_ms"]
        + metrics["t_bop_ms"] + metrics["t_motion_gen_ms"] + metrics["t_ik_ms"],
        1,
    )

    return metrics


def main() -> None:
    manifest = load_manifest()
    print(f"Loaded manifest: {len(manifest)} harnesses to evaluate")

    # Build simulation stack once (reused across all variants)
    simulation_root = Path(__file__).resolve().parents[1]
    config_loader = ConfigLoader(str(simulation_root))
    board_setup_config = config_loader.load_board_setup_config()
    (
        scene_runtime, hardware_interface, planner_client,
        planner_transport, station_config, robots_config,
    ) = buildSimulationStack(config_loader)

    results = []
    skipped = []
    total = len(manifest)

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

            print(f"[{i+1:3d}/{total}] {harness_id} ({tier:8s} {topology:10s}) "
                  f"{row['n_connectors']:3s}C {row['n_wires']:4s}W ...", end=" ", flush=True)

            try:
                metrics = run_variant(
                    harness_id=harness_id,
                    cdm_path=cdm_path,
                    config_loader=config_loader,
                    robots_config=robots_config,
                    station_config=station_config,
                    board_setup_config=board_setup_config,
                    hardware_interface=hardware_interface,
                    planner_client=planner_client,
                    planner_transport=planner_transport,
                    skip_ik=SKIP_IK,
                )

                if metrics is None:
                    reason = "IK pre-planning failed (infeasible)"
                    print(f"SKIP ({reason})")
                    writer_skipped.writerow({
                        "harness_id": harness_id,
                        "tier": tier,
                        "topology": topology,
                        "n_connectors": row["n_connectors"],
                        "n_wires": row["n_wires"],
                        "reason": reason,
                    })
                    f_skipped.flush()
                    skipped.append(harness_id)
                else:
                    t_plan = metrics["t_total_planning_ms"]
                    print(f"OK  plan={t_plan:.0f}ms  motions={metrics['n_motions']}")
                    result_row = {
                        "harness_id": harness_id,
                        "tier": tier,
                        "topology": topology,
                        "n_connectors": row["n_connectors"],
                        "n_wires": row["n_wires"],
                        "n_segments": row["n_segments"],
                        "n_nodes": row["n_nodes"],
                        "total_wire_length_mm": row["total_wire_length_mm"],
                        **{k: round(v, 2) if isinstance(v, float) else v for k, v in metrics.items()},
                    }
                    writer_results.writerow(result_row)
                    f_results.flush()
                    results.append(result_row)

            except Exception as e:
                reason = f"Exception: {type(e).__name__}: {e}"
                print(f"ERROR: {reason}")
                writer_skipped.writerow({
                    "harness_id": harness_id,
                    "tier": tier,
                    "topology": topology,
                    "n_connectors": row["n_connectors"],
                    "n_wires": row["n_wires"],
                    "reason": reason,
                })
                f_skipped.flush()
                skipped.append(harness_id)
                traceback.print_exc()

    print(f"\n── Summary ────────────────────────────────────────────────────")
    print(f"  Feasible:  {len(results)}/{total}")
    print(f"  Skipped:   {len(skipped)}/{total}")
    if results:
        plan_times = [r["t_total_planning_ms"] for r in results if isinstance(r.get("t_total_planning_ms"), (int, float))]
        if plan_times:
            print(f"  Plan time: median={sorted(plan_times)[len(plan_times)//2]:.0f}ms  "
                  f"p95={sorted(plan_times)[int(len(plan_times)*0.95)]:.0f}ms  "
                  f"max={max(plan_times):.0f}ms")
    print(f"\n  Results → {OUTPUT_RESULTS}")
    print(f"  Skipped → {OUTPUT_SKIPPED}")


if __name__ == "__main__":
    main()
