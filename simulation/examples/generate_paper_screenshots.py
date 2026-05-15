"""
Generate a 3-panel composite screenshot of the board setup phase for the paper.

Runs the board setup headlessly for the medium (Arena 2036 Robotics Challenge)
harness, captures offscreen MuJoCo renders at three evenly spaced moments
(early, mid, completed), and saves a horizontal composite to:

    698f3ae54d2ddb0627e27162/figures/simulation_screenshot.png

Run from the project root:
    python simulation/examples/generate_paper_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# ── project root on path ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import mujoco
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulation.examples.board_setup.BoardSetupRunner import (
    buildSimulationStack,
    printPlanSummary,
)
from simulation.examples.board_setup.OverlayEventAdapter import (
    processOverlayEvents,
    updateCarriedObjectsToTcp,
)
from simulation.core.ConfigLoader import ConfigLoader
from simulation.planning.BoardSetupExecutor import BoardSetupExecutor
from simulation.planning.GraspOrientationPlanner import GraspOrientationPlanner
from simulation.planning.LayoutToSimulationBridge import (
    generateLayout,
    generateMotionPlans,
    loadHarnessFromJson,
)
from simulation.planning.OrientationSource import RandomOrientationSource
from simulation.planning.TrajectoryCollisionChecker import (
    SharedAreaPolicy,
    TrajectoryCollisionChecker,
)
from simulation.planning.TrajectoryStore import TrajectoryStore
from simulation.planning.WorkspaceCoordinator import WorkspaceCoordinator
from simulation.core.CoordinateTransform import (
    AxisMapping,
    BoardToWorldTransform,
    WorldToRobotBaseTransform,
)
from simulation.visualization.SceneObjectOverlay import SceneObjectOverlay

# ── paths ─────────────────────────────────────────────────────────────────────
CDM_FILE = str(PROJECT_ROOT / "public" / "cdm" / "examples" / "complex_harness.json")
OUTPUT_PATH = PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures" / "simulation_screenshot.png"

# ── camera settings (matching viewer defaults) ─────────────────────────────────
CAM_AZIMUTH   = 270.0   # long-side: table foreground, robots behind
CAM_ELEVATION = -22.0   # shallower tilt — tops of robots visible, feet cropped
CAM_DISTANCE  = 1.55
CAM_LOOKAT    = [0.0, 0.0, 1.10]  # look at upper robot body level

RENDER_WIDTH  = 640
RENDER_HEIGHT = 360


def _render_frame(
    scene_runtime,
    scene_overlay: SceneObjectOverlay,
    tcp_site_ids: dict,
) -> np.ndarray:
    """Render one offscreen frame with robot + overlay objects."""
    renderer = mujoco.Renderer(scene_runtime.model, height=RENDER_HEIGHT, width=RENDER_WIDTH)

    # Configure camera
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.azimuth   = CAM_AZIMUTH
    cam.elevation = CAM_ELEVATION
    cam.distance  = CAM_DISTANCE
    cam.lookat[:] = CAM_LOOKAT

    # Disable contact viz for clean look
    opt = mujoco.MjvOption()
    mujoco.mjv_defaultOption(opt)
    opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = False
    opt.flags[mujoco.mjtVisFlag.mjVIS_CONTACTFORCE] = False
    opt.frame = mujoco.mjtFrame.mjFRAME_NONE

    renderer.update_scene(scene_runtime.data, camera=cam, scene_option=opt)

    # Add overlay objects (pegs, holders) to the scene
    updateCarriedObjectsToTcp(scene_overlay, scene_runtime, tcp_site_ids)
    scene_overlay.renderAll(renderer.scene)

    return renderer.render()


def main() -> None:
    print("=" * 60)
    print("Paper Screenshot Generator — Board Setup Phase")
    print("=" * 60)

    print(f"\n[1] Loading CDM: {CDM_FILE}")
    harness = loadHarnessFromJson(CDM_FILE)
    print(f"    {harness.id} ({harness.part_number})")

    simulation_root = Path(__file__).resolve().parents[1]
    config_loader = ConfigLoader(str(simulation_root))

    print("\n[2] Loading config + generating layout...")
    board_setup_config = config_loader.load_board_setup_config()
    layout_result = generateLayout(
        harness,
        cdm_file_path=CDM_FILE,
        intersection_offset_mm=board_setup_config.intersection_offset_mm,
    )
    print(f"    Board: {layout_result.board_width_mm:.0f} x {layout_result.board_height_mm:.0f} mm")

    print("\n[3] Building simulation stack...")
    (
        scene_runtime, hardware_interface, planner_client,
        planner_transport, station_config, robots_config,
    ) = buildSimulationStack(config_loader)

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

    print("\n[4] Generating motion plans...")
    motion_plans = generateMotionPlans(
        harness=harness,
        layout_result=layout_result,
        board_setup_config=board_setup_config,
        board_transform=board_transform,
        robot_definitions=robots_config.robots,
    )
    printPlanSummary(motion_plans)

    print("\n[5] Pre-planning trajectories...")
    robot_base_positions = {
        r.robot_name: tuple(r.base_position_m) for r in robots_config.robots
    }
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
        board_setup_config=board_setup_config,
    )
    setup_result = executor.prequeuePlans(motion_plans)

    if not setup_result.success:
        print(f"Pre-planning FAILED: {setup_result.failure_message}")
        sys.exit(1)

    total_s = setup_result.total_duration_s
    print(f"    Sequence ready: {total_s:.1f} s total")

    # ── build TCP site ID map ──────────────────────────────────────────────────
    tcp_site_ids = {}
    for robot_name, site_name in scene_runtime.robot_tcp_sites.items():
        site_id = mujoco.mj_name2id(scene_runtime.model, mujoco.mjtObj.mjOBJ_SITE, site_name)
        if site_id >= 0:
            tcp_site_ids[robot_name] = site_id

    # ── capture 4 frames at 10 %, 37 %, 63 %, 90 % of total duration ─────────
    capture_fractions = [0.22, 0.45, 0.67, 0.90]
    frames = []
    capture_times = []
    processed_indices: set = set()

    scene_overlay = SceneObjectOverlay()

    print("\n[6] Capturing frames...")
    for fraction in capture_fractions:
        target_t = fraction * total_s
        print(f"    t={target_t:.1f}s ({fraction*100:.0f}%)")

        hardware_interface.stepToTimestamp(target_t)
        current_t = hardware_interface.getCurrentTimestamp()
        capture_times.append(current_t)

        processOverlayEvents(
            scene_overlay, setup_result.overlay_events,
            current_t, processed_indices,
        )

        frame = _render_frame(scene_runtime, scene_overlay, tcp_site_ids)
        frames.append(frame)

    # ── composite into 2×2 grid ───────────────────────────────────────────────
    print("\n[7] Compositing frames...")
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 7})
    fig, axes = plt.subplots(2, 2, figsize=(8, 5))

    panel_labels = ["(a)", "(b)", "(c)", "(d)"]
    for ax, frame, panel_label, t in zip(axes.flat, frames, panel_labels, capture_times):
        ax.imshow(frame)
        ax.set_axis_off()
        ax.set_title(f"{panel_label}  $t = {t:.0f}$ s", fontsize=7, pad=3)

    fig.tight_layout(pad=0.3)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(OUTPUT_PATH), dpi=200, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    print(f"\nSaved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
