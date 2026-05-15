"""
Run the simulation scene and optionally open MuJoCo viewer.
"""

import argparse
import os
import time
from pathlib import Path

from simulation.core.ConfigLoader import ConfigLoader
from simulation.core.SceneBuilder import SceneBuilder
from simulation.examples.ViewerSupport import probe_viewer_support

try:
    import mujoco
    import mujoco.viewer
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore


def run_with_viewer(simulation_root_path: Path, duration_seconds: float) -> None:
    if mujoco is None:
        raise RuntimeError("MuJoCo is not installed.")

    config_loader = ConfigLoader(str(simulation_root_path))
    scene_runtime = SceneBuilder(
        station_config=config_loader.load_station_config(),
        robots_config=config_loader.load_robots_config(),
        grippers_config=config_loader.load_grippers_config(),
        scene_objects_config=config_loader.load_scene_objects_config(),
    ).build()

    with mujoco.viewer.launch_passive(scene_runtime.model, scene_runtime.data) as viewer:
        start_time = time.time()
        while viewer.is_running() and (time.time() - start_time) < duration_seconds:
            mujoco.mj_step(scene_runtime.model, scene_runtime.data)
            viewer.sync()
            time.sleep(scene_runtime.model.opt.timestep)

    os._exit(0)


def run_headless(simulation_root_path: Path, duration_seconds: float) -> None:
    if mujoco is None:
        raise RuntimeError("MuJoCo is not installed.")
    config_loader = ConfigLoader(str(simulation_root_path))
    scene_runtime = SceneBuilder(
        station_config=config_loader.load_station_config(),
        robots_config=config_loader.load_robots_config(),
        grippers_config=config_loader.load_grippers_config(),
        scene_objects_config=config_loader.load_scene_objects_config(),
    ).build()
    end_time = scene_runtime.data.time + duration_seconds
    while scene_runtime.data.time < end_time:
        mujoco.mj_step(scene_runtime.model, scene_runtime.data)
    print("Headless run completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dual robot simulation scene.")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds.")
    parser.add_argument("--no-viewer", action="store_true", help="Run without viewer.")
    parser.add_argument(
        "--force-viewer",
        action="store_true",
        help="Bypass viewer environment checks.",
    )
    args = parser.parse_args()

    simulation_root_path = Path(__file__).resolve().parent.parent
    if args.no_viewer:
        run_headless(simulation_root_path, args.duration)
    else:
        is_supported, reason_message = probe_viewer_support()
        if not is_supported and not args.force_viewer:
            print(f"Viewer disabled: {reason_message}")
            print("Falling back to headless mode.")
            run_headless(simulation_root_path, args.duration)
            return
        run_with_viewer(simulation_root_path, args.duration)


if __name__ == "__main__":
    main()
