"""
Layer A backend executor.

Responsibilities:
- own MuJoCo stepping
- apply timestamped setpoints
- expose feedback, FTS data, and backend errors
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from simulation.core.RotationUtils import rotationMatrixToQuatWxyz
from simulation.core.SceneBuilder import SceneRuntime
from simulation.interface.HardwareInterfaceModels import (
    FtsWrench,
    InterfaceErrorSeverity,
    RobotError,
    RobotFeedback,
    TimedSetpoint,
)

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore


@dataclass
class _RobotCommandState:
    queued_setpoints: List[TimedSetpoint]
    active_setpoint: Optional[TimedSetpoint]
    last_received_timestamp_s: float


class SimulationExecutor:
    def __init__(self, scene_runtime: SceneRuntime, control_frequency_hz: float = 125.0) -> None:
        if mujoco is None:
            raise RuntimeError("MuJoCo is not installed.")
        self.scene_runtime = scene_runtime
        self.control_frequency_hz = control_frequency_hz
        self.tick_period_s = 1.0 / max(control_frequency_hz, 1.0)
        self.current_timestamp_s = 0.0

        self.robot_command_states: Dict[str, _RobotCommandState] = {}
        self.robot_errors: Dict[str, List[RobotError]] = {}
        self.robot_joint_qpos_addresses: Dict[str, List[int]] = {}
        self.robot_tcp_site_ids: Dict[str, int] = {}
        self.robot_gripper_actuator_ids: Dict[str, int] = {}
        self.robot_joint_actuator_ids: Dict[str, List[int]] = {}
        self.robot_fts_sensor_ids: Dict[str, Dict[str, int]] = {}

        self._initialize_robot_state()

    def _initialize_robot_state(self) -> None:
        for robot_name, joint_names in self.scene_runtime.robot_joint_names.items():
            self.robot_command_states[robot_name] = _RobotCommandState(
                queued_setpoints=[],
                active_setpoint=None,
                last_received_timestamp_s=-1.0,
            )
            self.robot_errors[robot_name] = []

            qpos_addresses: List[int] = []
            for joint_name in joint_names:
                joint_id = mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
                qpos_addresses.append(self.scene_runtime.model.jnt_qposadr[joint_id])
            self.robot_joint_qpos_addresses[robot_name] = qpos_addresses

            site_name = self.scene_runtime.robot_tcp_sites[robot_name]
            site_id = mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_SITE, site_name)
            self.robot_tcp_site_ids[robot_name] = site_id

            gripper_actuator_name = self.scene_runtime.robot_gripper_actuators[robot_name]
            gripper_actuator_id = mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_ACTUATOR, gripper_actuator_name)
            self.robot_gripper_actuator_ids[robot_name] = gripper_actuator_id

            actuator_ids: List[int] = []
            for actuator_name in self.scene_runtime.robot_joint_actuators[robot_name]:
                actuator_ids.append(mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator_name))
            self.robot_joint_actuator_ids[robot_name] = actuator_ids

            force_sensor_name = f"{robot_name}/fts_force"
            torque_sensor_name = f"{robot_name}/fts_torque"
            force_sensor_id = mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_SENSOR, force_sensor_name)
            torque_sensor_id = mujoco.mj_name2id(self.scene_runtime.model, mujoco.mjtObj.mjOBJ_SENSOR, torque_sensor_name)
            self.robot_fts_sensor_ids[robot_name] = {
                "force": force_sensor_id,
                "torque": torque_sensor_id,
            }

    def queue_setpoint(self, timed_setpoint: TimedSetpoint) -> None:
        robot_name = timed_setpoint.robot_name
        with self.scene_runtime.simulation_lock:
            command_state = self.robot_command_states[robot_name]
            command_state.queued_setpoints.append(timed_setpoint)
            command_state.queued_setpoints.sort(key=lambda setpoint_item: setpoint_item.timestamp_s)
            command_state.last_received_timestamp_s = max(command_state.last_received_timestamp_s, timed_setpoint.timestamp_s)

    def step_to_timestamp(self, target_timestamp_s: float) -> int:
        if target_timestamp_s < self.current_timestamp_s:
            return 0

        executed_ticks = 0
        with self.scene_runtime.simulation_lock:
            while self.current_timestamp_s + 1e-12 < target_timestamp_s:
                self._apply_due_setpoints()
                self._step_single_tick()
                self.current_timestamp_s += self.tick_period_s
                executed_ticks += 1
        return executed_ticks

    def _apply_due_setpoints(self) -> None:
        for robot_name, command_state in self.robot_command_states.items():
            while command_state.queued_setpoints and command_state.queued_setpoints[0].timestamp_s <= self.current_timestamp_s + 1e-12:
                command_state.active_setpoint = command_state.queued_setpoints.pop(0)

            active_setpoint = command_state.active_setpoint
            if active_setpoint is None:
                continue

            if active_setpoint.joint_angles is not None:
                self._apply_joint_setpoint(robot_name, active_setpoint.joint_angles)
            if active_setpoint.gripper_command_value is not None:
                self._apply_gripper_setpoint(robot_name, active_setpoint.gripper_command_value)

    def _apply_joint_setpoint(self, robot_name: str, joint_angles: List[float]) -> None:
        actuator_ids = self.robot_joint_actuator_ids[robot_name]
        for index, actuator_id in enumerate(actuator_ids):
            if 0 <= actuator_id < self.scene_runtime.model.nu:
                self.scene_runtime.data.ctrl[actuator_id] = float(joint_angles[index])

    def _apply_gripper_setpoint(self, robot_name: str, gripper_command_value: float) -> None:
        actuator_id = self.robot_gripper_actuator_ids[robot_name]
        if 0 <= actuator_id < self.scene_runtime.model.nu:
            self.scene_runtime.data.ctrl[actuator_id] = float(gripper_command_value)

    def _step_single_tick(self) -> None:
        timestep_seconds = float(self.scene_runtime.model.opt.timestep)
        steps_per_tick = max(1, int(round(self.tick_period_s / max(timestep_seconds, 1e-6))))
        for _ in range(steps_per_tick):
            mujoco.mj_step(self.scene_runtime.model, self.scene_runtime.data)

    def get_feedback(self, robot_name: str) -> RobotFeedback:
        with self.scene_runtime.simulation_lock:
            joint_angles = [
                float(self.scene_runtime.data.qpos[qpos_address])
                for qpos_address in self.robot_joint_qpos_addresses[robot_name]
            ]
            tcp_position_m, tcp_quat_wxyz = self._get_tcp_pose(robot_name)
            gripper_value = self._get_gripper_command(robot_name)
            fts_data = self._get_fts_data(robot_name)

            return RobotFeedback(
                robot_name=robot_name,
                timestamp_s=self.current_timestamp_s,
                joint_angles=joint_angles,
                tcp_position_m=tcp_position_m,
                tcp_quat_wxyz=tcp_quat_wxyz,
                gripper_command_value=gripper_value,
                fts_wrench=FtsWrench(
                    force_xyz_n=fts_data["force_xyz_n"],
                    torque_xyz_nm=fts_data["torque_xyz_nm"],
                ),
            )

    def pop_robot_errors(self, robot_name: str) -> List[RobotError]:
        with self.scene_runtime.simulation_lock:
            error_list = self.robot_errors[robot_name]
            self.robot_errors[robot_name] = []
            return error_list

    def add_robot_error(
        self,
        robot_name: str,
        error_code: str,
        message: str,
        severity: InterfaceErrorSeverity = InterfaceErrorSeverity.ERROR,
        context: Optional[Dict[str, str]] = None,
    ) -> None:
        if context is None:
            context = {}
        with self.scene_runtime.simulation_lock:
            self.robot_errors[robot_name].append(
                RobotError(
                    robot_name=robot_name,
                    timestamp_s=self.current_timestamp_s,
                    error_code=error_code,
                    message=message,
                    severity=severity,
                    context=context,
                )
            )

    def _get_tcp_pose(self, robot_name: str) -> tuple[List[float], List[float]]:
        site_id = self.robot_tcp_site_ids[robot_name]
        position_xyz = self.scene_runtime.data.site_xpos[site_id].copy().tolist()
        rotation_matrix = self.scene_runtime.data.site_xmat[site_id].reshape(3, 3).copy()
        quat_wxyz = list(rotationMatrixToQuatWxyz(rotation_matrix))
        return position_xyz, quat_wxyz

    def _get_gripper_command(self, robot_name: str) -> float:
        actuator_id = self.robot_gripper_actuator_ids[robot_name]
        if 0 <= actuator_id < self.scene_runtime.model.nu:
            return float(self.scene_runtime.data.ctrl[actuator_id])
        return 0.0

    def _get_fts_data(self, robot_name: str) -> Dict[str, List[float]]:
        force_data = [0.0, 0.0, 0.0]
        torque_data = [0.0, 0.0, 0.0]

        force_sensor_id = self.robot_fts_sensor_ids[robot_name]["force"]
        torque_sensor_id = self.robot_fts_sensor_ids[robot_name]["torque"]

        if force_sensor_id >= 0:
            force_address = self.scene_runtime.model.sensor_adr[force_sensor_id]
            force_dimension = self.scene_runtime.model.sensor_dim[force_sensor_id]
            force_values = self.scene_runtime.data.sensordata[force_address: force_address + force_dimension]
            force_data = [float(value_item) for value_item in force_values]

        if torque_sensor_id >= 0:
            torque_address = self.scene_runtime.model.sensor_adr[torque_sensor_id]
            torque_dimension = self.scene_runtime.model.sensor_dim[torque_sensor_id]
            torque_values = self.scene_runtime.data.sensordata[torque_address: torque_address + torque_dimension]
            torque_data = [float(value_item) for value_item in torque_values]

        return {
            "force_xyz_n": force_data,
            "torque_xyz_nm": torque_data,
        }


