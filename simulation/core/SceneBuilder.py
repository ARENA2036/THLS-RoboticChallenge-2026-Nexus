"""
Scene builder for MuJoCo dual-robot simulation.

This builder uses the real UR10e + Robotiq 2F-85 scene from `cable_handling`,
while adding configurable peg and connector-holder visuals and disabling
elastic cable physics.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import threading

from .ConfigModels import GrippersConfig, RobotsConfig, SceneObjectsConfig, StationConfig

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore


@dataclass
class SceneRuntime:
    model: "mujoco.MjModel"
    data: "mujoco.MjData"
    robot_joint_actuators: Dict[str, List[str]]
    robot_joint_names: Dict[str, List[str]]
    robot_tcp_sites: Dict[str, str]
    robot_gripper_actuators: Dict[str, str]
    simulation_lock: threading.RLock


class SceneBuilder:
    def __init__(
        self,
        station_config: StationConfig,
        robots_config: RobotsConfig,
        grippers_config: GrippersConfig,
        scene_objects_config: SceneObjectsConfig,
    ) -> None:
        self.station_config = station_config
        self.robots_config = robots_config
        self.grippers_config = grippers_config
        self.scene_objects_config = scene_objects_config

    def build(self) -> SceneRuntime:
        if mujoco is None:
            raise RuntimeError("MuJoCo is not installed. Install `mujoco` to build scene.")
        model_loader_module = self._load_model_loader_module()

        cable_handling_models_path = Path(__file__).resolve().parents[2] / "cable_handling" / "models"
        scene_path, robot_path = model_loader_module.get_model_paths(str(cable_handling_models_path))

        robot_map = {robot_definition.robot_name: robot_definition for robot_definition in self.robots_config.robots}
        left_robot = robot_map["left"]
        right_robot = robot_map["right"]
        left_mount_pose = [*left_robot.base_position_m, *left_robot.base_quat_wxyz]
        right_mount_pose = [*right_robot.base_position_m, *right_robot.base_quat_wxyz]

        peg_visuals = self._to_peg_visual_payload()
        holder_visuals = self._to_holder_visual_payload()
        plug_visuals = self._to_plug_visual_payload()

        model = model_loader_module.load_dual_robot_scene(
            scene_path=scene_path,
            robot_path=robot_path,
            left_mount_pose=left_mount_pose,
            right_mount_pose=right_mount_pose,
            peg_visuals=peg_visuals,
            holder_visuals=holder_visuals,
            plug_visuals=plug_visuals,
        )
        data = mujoco.MjData(model)

        robot_joint_actuators: Dict[str, List[str]] = {}
        robot_joint_names: Dict[str, List[str]] = {}
        robot_tcp_sites: Dict[str, str] = {}
        robot_gripper_actuators: Dict[str, str] = {}

        for robot_definition in self.robots_config.robots:
            robot_name = robot_definition.robot_name
            robot_joint_actuators[robot_name] = [f"{robot_name}/shoulder_pan", f"{robot_name}/shoulder_lift", f"{robot_name}/elbow", f"{robot_name}/wrist_1", f"{robot_name}/wrist_2", f"{robot_name}/wrist_3"]
            robot_joint_names[robot_name] = [
                f"{robot_name}/shoulder_pan_joint",
                f"{robot_name}/shoulder_lift_joint",
                f"{robot_name}/elbow_joint",
                f"{robot_name}/wrist_1_joint",
                f"{robot_name}/wrist_2_joint",
                f"{robot_name}/wrist_3_joint",
            ]
            robot_tcp_sites[robot_name] = f"{robot_name}/tcp_site"
            robot_gripper_actuators[robot_name] = f"{robot_name}/gripper"

        scene_runtime = SceneRuntime(
            model=model,
            data=data,
            robot_joint_actuators=robot_joint_actuators,
            robot_joint_names=robot_joint_names,
            robot_tcp_sites=robot_tcp_sites,
            robot_gripper_actuators=robot_gripper_actuators,
            simulation_lock=threading.RLock(),
        )
        self._apply_home_configuration(scene_runtime)
        return scene_runtime
    def _load_model_loader_module(self):
        import importlib.util

        module_path = Path(__file__).resolve().parents[2] / "cable_handling" / "src" / "model_loader.py"
        spec = importlib.util.spec_from_file_location("cable_model_loader", str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load model loader module from: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _to_peg_visual_payload(self) -> List[dict]:
        peg_payloads: List[dict] = []
        for peg_instance in self.scene_objects_config.peg_instances:
            peg_shape = self.scene_objects_config.peg_catalog[peg_instance.peg_type]
            peg_payloads.append(
                {
                    "object_id": peg_instance.object_id,
                    "position_m": list(peg_instance.position_m),
                    "orientation_quat_wxyz": list(peg_instance.orientation_quat_wxyz),
                    "peg_shape_type": peg_shape.peg_shape_type,
                    "post_radius_m": peg_shape.post_radius_m,
                    "post_height_m": peg_shape.post_height_m,
                    "prong_length_m": peg_shape.prong_length_m,
                    "prong_width_m": peg_shape.prong_width_m,
                    "prong_gap_m": peg_shape.prong_gap_m,
                    "crossbar_length_m": peg_shape.crossbar_length_m,
                    "crossbar_width_m": peg_shape.crossbar_width_m,
                    "color_rgba": list(peg_instance.color_rgba),
                }
            )
        return peg_payloads

    def _to_holder_visual_payload(self) -> List[dict]:
        holder_payloads: List[dict] = []
        for holder_instance in self.scene_objects_config.connector_holder_instances:
            holder_payloads.append(
                {
                    "object_id": holder_instance.object_id,
                    "position_m": list(holder_instance.position_m),
                    "orientation_quat_wxyz": list(holder_instance.orientation_quat_wxyz),
                    "size_m": list(holder_instance.size_m),
                    "color_rgba": list(holder_instance.color_rgba),
                }
            )
        return holder_payloads

    def _to_plug_visual_payload(self) -> List[dict]:
        plug_payloads: List[dict] = []
        for plug_instance in self.scene_objects_config.connector_plug_instances:
            plug_payloads.append(
                {
                    "object_id": plug_instance.object_id,
                    "position_m": list(plug_instance.position_m),
                    "orientation_quat_wxyz": list(plug_instance.orientation_quat_wxyz),
                    "plug_radius_m": plug_instance.plug_radius_m,
                    "plug_length_m": plug_instance.plug_length_m,
                    "color_rgba": list(plug_instance.color_rgba),
                }
            )
        return plug_payloads

    def _apply_home_configuration(self, scene_runtime: SceneRuntime) -> None:
        for robot_definition in self.robots_config.robots:
            robot_name = robot_definition.robot_name
            actuator_names = scene_runtime.robot_joint_actuators[robot_name]
            for index, actuator_name in enumerate(actuator_names):
                actuator_id = mujoco.mj_name2id(scene_runtime.model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator_name)
                if actuator_id >= 0:
                    scene_runtime.data.ctrl[actuator_id] = robot_definition.home_joint_angles_rad[index]
            gripper_name = scene_runtime.robot_gripper_actuators[robot_name]
            gripper_id = mujoco.mj_name2id(scene_runtime.model, mujoco.mjtObj.mjOBJ_ACTUATOR, gripper_name)
            if gripper_id >= 0:
                scene_runtime.data.ctrl[gripper_id] = 0.0
        mujoco.mj_forward(scene_runtime.model, scene_runtime.data)

