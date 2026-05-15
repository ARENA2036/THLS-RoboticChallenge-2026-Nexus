"""
Dual-robot demo with MoveJ, MoveL, and gripper commands.

All motions and gripper actions are pre-planned and their setpoints
queued with absolute timestamps. The viewer loop then drives the
simulation forward at wall-clock pace so you can watch the robots
move and grip in real time.

MoveJ  -- large joint-space reconfigurations (approach, transfer, home).
MoveL  -- short straight-line Cartesian motions (pick down, lift up, place).

Path visualisation is driven by timestamp-based recording triggers that
map motion segments to named, coloured cable paths rendered as 3-D
capsule tubes in the MuJoCo viewer overlay.
"""

import argparse
import os
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from simulation.backend.SimulationExecutor import SimulationExecutor
from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.SceneBuilder import SceneBuilder
from simulation.examples.ViewerSupport import probe_viewer_support
from simulation.interface.SimulationHardwareAdapter import SimulationHardwareAdapter
from simulation.planning.MoveItPlannerClient import PlannerClient
from simulation.planning.PinocchioCartesianTransport import PinocchioCartesianTransport
from simulation.planning.PlanningModels import MoveJRequest, MoveLRequest, PoseTarget
from simulation.visualization.PathRecorder import PathRecorder
from simulation.visualization.PathRenderer import PathRenderer
from simulation.visualization.VisualizationModels import RecordingWindow

try:
    import mujoco
    import mujoco.viewer
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore

HOME_JOINT_ANGLES = [0.0, -1.57, 1.57, -1.57, -1.57, 0.0]
GRIPPER_OPEN = 0.0
GRIPPER_CLOSE = 255.0

LEFT_APPROACH_QUAT  = [-0.0813, 0.7360, -0.6632, -0.1087]
RIGHT_APPROACH_QUAT = [-0.0909, -0.6652, 0.7377, -0.0708]
LEFT_PLACE_QUAT     = [-0.1664, 0.7382, -0.6394, -0.1359]
RIGHT_PLACE_QUAT    = [-0.1166, -0.6436, 0.7393, -0.1601]

LEFT_CABLE_COLOR: Tuple[float, float, float, float] = (0.1, 0.75, 0.25, 1.0)
RIGHT_CABLE_COLOR: Tuple[float, float, float, float] = (0.9, 0.3, 0.1, 1.0)
CABLE_TUBE_RADIUS_M = 0.004


class DemoStep(NamedTuple):
    step_type: str
    robot_name: str
    label: str
    data: object
    duration_s: float


DEMO_SEQUENCE: List[DemoStep] = [
    DemoStep("gripper", "left",  "Left  open gripper",       GRIPPER_OPEN,  0.3),
    DemoStep("gripper", "right", "Right open gripper",        GRIPPER_OPEN,  0.3),

    DemoStep("movej", "left",  "Left  MoveJ -> approach",     [0.30, -1.20, 1.20, -1.60, -1.30, 0.20],   2.0),
    DemoStep("movej", "right", "Right MoveJ -> approach",     [-0.30, -1.20, 1.20, -1.60, -1.80, -0.20],  2.0),

    DemoStep("movel", "left",  "Left  MoveL down pick",
        PoseTarget(position_m=[0.8057, 0.5126, 0.3765], quat_wxyz=LEFT_APPROACH_QUAT), 1.5),
    DemoStep("movel", "right", "Right MoveL down pick",
        PoseTarget(position_m=[0.9121, -0.1690, 0.3735], quat_wxyz=RIGHT_APPROACH_QUAT), 1.5),

    DemoStep("gripper", "left",  "Left  close gripper",      GRIPPER_CLOSE, 0.5),
    DemoStep("gripper", "right", "Right close gripper",       GRIPPER_CLOSE, 0.5),

    DemoStep("movel", "left",  "Left  MoveL up lift",
        PoseTarget(position_m=[0.8057, 0.5126, 0.4765], quat_wxyz=LEFT_APPROACH_QUAT), 1.5),
    DemoStep("movel", "right", "Right MoveL up lift",
        PoseTarget(position_m=[0.9121, -0.1690, 0.4735], quat_wxyz=RIGHT_APPROACH_QUAT), 1.5),

    DemoStep("movej", "left",  "Left  MoveJ -> place appr.",  [0.50, -1.00, 0.90, -1.70, -1.20, 0.40],   2.0),
    DemoStep("movej", "right", "Right MoveJ -> place appr.",  [-0.50, -1.00, 0.90, -1.70, -1.90, -0.40],  2.0),

    DemoStep("movel", "left",  "Left  MoveL down place",
        PoseTarget(position_m=[0.8119, 0.7616, 0.4179], quat_wxyz=LEFT_PLACE_QUAT), 1.5),
    DemoStep("movel", "right", "Right MoveL down place",
        PoseTarget(position_m=[0.9850, -0.4467, 0.4138], quat_wxyz=RIGHT_PLACE_QUAT), 1.5),

    DemoStep("gripper", "left",  "Left  open gripper",       GRIPPER_OPEN,  0.5),
    DemoStep("gripper", "right", "Right open gripper",        GRIPPER_OPEN,  0.5),

    DemoStep("movel", "left",  "Left  MoveL up retreat",
        PoseTarget(position_m=[0.8119, 0.7616, 0.5179], quat_wxyz=LEFT_PLACE_QUAT), 1.5),
    DemoStep("movel", "right", "Right MoveL up retreat",
        PoseTarget(position_m=[0.9850, -0.4467, 0.5138], quat_wxyz=RIGHT_PLACE_QUAT), 1.5),

    DemoStep("movej", "left",  "Left  MoveJ -> home",         HOME_JOINT_ANGLES, 2.0),
    DemoStep("movej", "right", "Right MoveJ -> home",          HOME_JOINT_ANGLES, 2.0),
]

RECORDING_TRIGGERS: Dict[str, Dict] = {
    "Left  MoveL up lift": {
        "segment_name": "left_cable_lift",
        "robot_name": "left",
        "color_rgba": LEFT_CABLE_COLOR,
    },
    "Right MoveL up lift": {
        "segment_name": "right_cable_lift",
        "robot_name": "right",
        "color_rgba": RIGHT_CABLE_COLOR,
    },
    "Left  MoveJ -> place appr.": {
        "segment_name": "left_cable_transfer",
        "robot_name": "left",
        "color_rgba": LEFT_CABLE_COLOR,
    },
    "Right MoveJ -> place appr.": {
        "segment_name": "right_cable_transfer",
        "robot_name": "right",
        "color_rgba": RIGHT_CABLE_COLOR,
    },
    "Left  MoveL down place": {
        "segment_name": "left_cable_place",
        "robot_name": "left",
        "color_rgba": LEFT_CABLE_COLOR,
    },
    "Right MoveL down place": {
        "segment_name": "right_cable_place",
        "robot_name": "right",
        "color_rgba": RIGHT_CABLE_COLOR,
    },
}


def _build_simulation_stack():
    simulation_root_path = Path(__file__).resolve().parent.parent
    config_loader = ConfigLoader(str(simulation_root_path))
    scene_runtime = SceneBuilder(
        station_config=config_loader.load_station_config(),
        robots_config=config_loader.load_robots_config(),
        grippers_config=config_loader.load_grippers_config(),
        scene_objects_config=config_loader.load_scene_objects_config(),
    ).build()
    simulation_executor = SimulationExecutor(scene_runtime=scene_runtime, control_frequency_hz=125.0)
    hardware_interface = SimulationHardwareAdapter(
        simulation_executor=simulation_executor, command_frequency_hz=125.0
    )
    planner_client = PlannerClient(
        planning_transport=PinocchioCartesianTransport()
    )
    path_recorder = PathRecorder(simulation_executor=simulation_executor)
    return scene_runtime, hardware_interface, planner_client, path_recorder


def _prequeue_all_steps(
    hardware_interface: SimulationHardwareAdapter,
    planner_client: PlannerClient,
) -> Tuple[float, List[RecordingWindow]]:
    """Plan every step, queue setpoints, and collect recording windows.

    Returns (total_duration_s, recording_windows).
    """
    current_time_s = 0.0
    last_joint_target: Dict[str, List[float]] = {
        "left": list(HOME_JOINT_ANGLES),
        "right": list(HOME_JOINT_ANGLES),
    }
    recording_windows: List[RecordingWindow] = []

    for step_index, step in enumerate(DEMO_SEQUENCE):
        tag = f"[{step_index + 1}/{len(DEMO_SEQUENCE)}]"
        end_time_s = current_time_s + step.duration_s

        if step.step_type == "gripper":
            gripper_value = float(step.data)
            print(f"  {tag} {step.label}  (t={current_time_s:.1f}s, val={gripper_value:.0f})")
            hardware_interface.sendTimedSetpoint(
                robot_name=step.robot_name,
                timestamp_s=current_time_s,
                gripper_command_value=gripper_value,
            )

        elif step.step_type == "movej":
            target_angles: List[float] = step.data  # type: ignore[assignment]
            print(f"  {tag} {step.label}  (t={current_time_s:.1f}s .. {end_time_s:.1f}s)")
            request_data = MoveJRequest(
                robot_name=step.robot_name,
                target_joint_angles=target_angles,
                start_joint_angles=last_joint_target[step.robot_name],
                duration_s=step.duration_s,
            )
            planning_result = planner_client.plan_movej(request_data)
            if not planning_result.success:
                print(f"    FAIL: MoveJ planning failed")
                current_time_s = end_time_s
                continue

            for point in planning_result.trajectory:
                hardware_interface.sendTimedSetpoint(
                    robot_name=step.robot_name,
                    timestamp_s=current_time_s + point.timestamp_s,
                    joint_angles=point.joint_angles,
                    gripper_command_value=point.gripper_command_value,
                )
            last_joint_target[step.robot_name] = list(target_angles)

        elif step.step_type == "movel":
            pose_target: PoseTarget = step.data  # type: ignore[assignment]
            print(f"  {tag} {step.label}  (t={current_time_s:.1f}s .. {end_time_s:.1f}s)")
            request_data = MoveLRequest(
                robot_name=step.robot_name,
                target_pose=pose_target,
                start_joint_angles=last_joint_target[step.robot_name],
                duration_s=step.duration_s,
            )
            planning_result = planner_client.plan_movel(request_data)
            if not planning_result.success:
                error_msg = planning_result.planning_error.message if planning_result.planning_error else "unknown"
                print(f"    FAIL: MoveL planning failed -- {error_msg}")
                current_time_s = end_time_s
                continue

            for point in planning_result.trajectory:
                hardware_interface.sendTimedSetpoint(
                    robot_name=step.robot_name,
                    timestamp_s=current_time_s + point.timestamp_s,
                    joint_angles=point.joint_angles,
                    gripper_command_value=point.gripper_command_value,
                )
            last_joint_target[step.robot_name] = list(planning_result.trajectory[-1].joint_angles)

        if step.label in RECORDING_TRIGGERS:
            trigger = RECORDING_TRIGGERS[step.label]
            recording_windows.append(
                RecordingWindow(
                    segment_name=trigger["segment_name"],
                    robot_name=trigger["robot_name"],
                    start_time_s=current_time_s,
                    end_time_s=end_time_s,
                    color_rgba=trigger["color_rgba"],
                )
            )

        current_time_s = end_time_s

    return current_time_s, recording_windows


def _run_viewer_with_path_overlay(
    scene_runtime,
    hardware_interface: SimulationHardwareAdapter,
    path_recorder: PathRecorder,
    path_renderer: PathRenderer,
    recording_windows: List[RecordingWindow],
    total_playback_s: float,
    is_keep_open: bool,
    export_path: Optional[str],
) -> None:
    with mujoco.viewer.launch_passive(scene_runtime.model, scene_runtime.data) as viewer:
        viewer.cam.azimuth = 150.0
        viewer.cam.elevation = -35.0
        viewer.cam.distance = 4.5
        viewer.cam.lookat[:] = [0.0, 0.0, 0.85]

        active_window_names: Set[str] = set()
        wall_start = time.time()

        while viewer.is_running():
            wall_elapsed = time.time() - wall_start

            if not is_keep_open and wall_elapsed >= total_playback_s:
                break

            if wall_elapsed < total_playback_s:
                hardware_interface.stepToTimestamp(wall_elapsed)

            for window in recording_windows:
                if window.segment_name not in active_window_names and wall_elapsed >= window.start_time_s:
                    path_recorder.startRecording(
                        robot_name=window.robot_name,
                        segment_name=window.segment_name,
                        color_rgba=window.color_rgba,
                        tube_radius_m=CABLE_TUBE_RADIUS_M,
                    )
                    active_window_names.add(window.segment_name)

                if window.segment_name in active_window_names and wall_elapsed >= window.end_time_s:
                    if path_recorder.segments[window.segment_name].is_recording:
                        path_recorder.stopRecording(window.segment_name)

            path_recorder.sampleCurrentPositions()

            if viewer.user_scn is not None:
                path_renderer.renderSegments(viewer.user_scn, path_recorder.getVisibleSegments())

            viewer.sync()
            time.sleep(0.008)

    if export_path:
        path_recorder.exportToJson(export_path)
        print(f"Path segments exported to {export_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dual-robot MoveJ + MoveL demo with real-time visualization.")
    parser.add_argument("--duration", type=float, default=2.0, help="Extra idle time after motions finish (seconds).")
    parser.add_argument("--viewer", action="store_true", help="Launch MuJoCo viewer for real-time playback.")
    parser.add_argument("--force-viewer", action="store_true", help="Bypass viewer environment checks.")
    parser.add_argument("--keep-open", action="store_true", help="Keep viewer open after playback (close manually).")
    parser.add_argument("--export-path", type=str, default=None, help="JSON file path to export recorded cable path segments.")
    args = parser.parse_args()

    if mujoco is None:
        raise RuntimeError("MuJoCo is not installed.")

    scene_runtime, hardware_interface, planner_client, path_recorder = _build_simulation_stack()
    path_renderer = PathRenderer()

    print("Pre-planning motion sequence...")
    total_motion_s, recording_windows = _prequeue_all_steps(hardware_interface, planner_client)
    total_playback_s = total_motion_s + args.duration
    print(f"Sequence ready: {total_motion_s:.1f}s of motion, {total_playback_s:.1f}s total playback")
    print(f"  {len(recording_windows)} cable recording windows configured")

    if not args.viewer:
        hardware_interface.stepToTimestamp(total_motion_s)
        print("Headless demo completed.")
        return

    is_supported, reason_message = probe_viewer_support()
    if not is_supported and not args.force_viewer:
        print(f"Viewer disabled: {reason_message}")
        hardware_interface.stepToTimestamp(total_motion_s)
        print("Headless fallback completed.")
        return

    _run_viewer_with_path_overlay(
        scene_runtime=scene_runtime,
        hardware_interface=hardware_interface,
        path_recorder=path_recorder,
        path_renderer=path_renderer,
        recording_windows=recording_windows,
        total_playback_s=total_playback_s,
        is_keep_open=args.keep_open,
        export_path=args.export_path,
    )

    os._exit(0)


if __name__ == "__main__":
    main()
