"""
Dual Robot Controller for Wire Harness Assembly Simulation

This module provides a Python interface for controlling two UR10e robots
with Robotiq 2F-85 grippers in a MuJoCo simulation environment.

Features:
- Joint space motion control
- Cartesian (linear) motion control with IK
- Unified (synchronized) and parallel motion execution
- Gripper open/close/position control
- Force-torque sensor reading
- Camera image capture
"""

import numpy as np
import mujoco
from typing import Optional, Tuple, List, Union
from enum import Enum
from dataclasses import dataclass
import threading
import time


class RobotSide(Enum):
    """Enum for robot identification."""
    LEFT = "left"
    RIGHT = "right"


@dataclass
class RobotState:
    """Data class for robot state information."""
    joint_positions: np.ndarray
    joint_velocities: np.ndarray
    tcp_position: np.ndarray
    tcp_orientation: np.ndarray
    gripper_position: float
    force_torque: np.ndarray


class DualRobotController:
    """
    Controller class for dual UR10e robots with Robotiq 2F-85 grippers.
    
    Provides unified interface for:
    - Joint motion control
    - Cartesian motion control
    - Gripper control
    - Sensor reading
    - Camera capture
    """
    
    # Robot configuration
    NUM_JOINTS = 6
    GRIPPER_OPEN = 0
    GRIPPER_CLOSED = 255
    
    # Joint names for each robot
    JOINT_NAMES = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint"
    ]
    
    # Actuator names for each robot
    ACTUATOR_NAMES = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow",
        "wrist_1",
        "wrist_2",
        "wrist_3"
    ]
    
    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData):
        """
        Initialize the dual robot controller.
        
        Args:
            model: MuJoCo model instance
            data: MuJoCo data instance
        """
        self.model = model
        self.data = data
        
        # Cache actuator and sensor indices for faster access
        self._initializeIndices()
        
        # Motion control state
        self._motion_in_progress = {RobotSide.LEFT: False, RobotSide.RIGHT: False}
        self._motion_lock = threading.Lock()
        
    def _initializeIndices(self):
        """Initialize actuator, joint, and sensor indices for both robots."""
        self.actuator_indices = {RobotSide.LEFT: {}, RobotSide.RIGHT: {}}
        self.joint_indices = {RobotSide.LEFT: {}, RobotSide.RIGHT: {}}
        self.sensor_indices = {RobotSide.LEFT: {}, RobotSide.RIGHT: {}}
        self.site_indices = {RobotSide.LEFT: {}, RobotSide.RIGHT: {}}
        
        for side in RobotSide:
            prefix = f"{side.value}/"
            
            # Actuator indices
            for name in self.ACTUATOR_NAMES:
                full_name = f"{prefix}{name}"
                actuator_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, full_name)
                if actuator_id >= 0:
                    self.actuator_indices[side][name] = actuator_id
            
            # Gripper actuator
            gripper_name = f"{prefix}gripper"
            gripper_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, gripper_name)
            if gripper_id >= 0:
                self.actuator_indices[side]["gripper"] = gripper_id
            
            # Joint indices
            for name in self.JOINT_NAMES:
                full_name = f"{prefix}{name}"
                joint_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, full_name)
                if joint_id >= 0:
                    self.joint_indices[side][name] = joint_id
            
            # Sensor indices (force-torque)
            fts_force_name = f"{prefix}fts_force"
            fts_torque_name = f"{prefix}fts_torque"
            
            for sensor_idx in range(self.model.nsensor):
                sensor_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_SENSOR, sensor_idx)
                if sensor_name == fts_force_name:
                    self.sensor_indices[side]["fts_force"] = sensor_idx
                elif sensor_name == fts_torque_name:
                    self.sensor_indices[side]["fts_torque"] = sensor_idx
            
            # Site indices (TCP, FTS)
            tcp_site_name = f"{prefix}tcp_site"
            fts_site_name = f"{prefix}fts_site"
            
            tcp_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, tcp_site_name)
            if tcp_id >= 0:
                self.site_indices[side]["tcp"] = tcp_id
                
            fts_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, fts_site_name)
            if fts_id >= 0:
                self.site_indices[side]["fts"] = fts_id

    # ==================== JOINT MOTION CONTROL ====================
    
    def getJointPositions(self, robot: RobotSide) -> np.ndarray:
        """
        Get current joint positions for specified robot.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Array of 6 joint positions in radians
        """
        positions = np.zeros(self.NUM_JOINTS)
        for idx, name in enumerate(self.JOINT_NAMES):
            joint_id = self.joint_indices[robot].get(name)
            if joint_id is not None:
                qpos_addr = self.model.jnt_qposadr[joint_id]
                positions[idx] = self.data.qpos[qpos_addr]
        return positions
    
    def getJointVelocities(self, robot: RobotSide) -> np.ndarray:
        """
        Get current joint velocities for specified robot.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Array of 6 joint velocities in rad/s
        """
        velocities = np.zeros(self.NUM_JOINTS)
        for idx, name in enumerate(self.JOINT_NAMES):
            joint_id = self.joint_indices[robot].get(name)
            if joint_id is not None:
                qvel_addr = self.model.jnt_dofadr[joint_id]
                velocities[idx] = self.data.qvel[qvel_addr]
        return velocities
    
    def setJointPositions(self, robot: RobotSide, joint_positions: np.ndarray):
        """
        Set target joint positions for specified robot (instant).
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            joint_positions: Array of 6 target joint positions in radians
        """
        if len(joint_positions) != self.NUM_JOINTS:
            raise ValueError(f"Expected {self.NUM_JOINTS} joint positions, got {len(joint_positions)}")
        
        for idx, name in enumerate(self.ACTUATOR_NAMES):
            actuator_id = self.actuator_indices[robot].get(name)
            if actuator_id is not None:
                self.data.ctrl[actuator_id] = joint_positions[idx]
    
    def moveJoints(self, robot: RobotSide, target_positions: np.ndarray, 
                   duration: float, steps_per_second: int = 500) -> List[np.ndarray]:
        """
        Generate trajectory for smooth joint motion.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            target_positions: Array of 6 target joint positions in radians
            duration: Motion duration in seconds
            steps_per_second: Trajectory resolution
            
        Returns:
            List of joint position waypoints
        """
        if len(target_positions) != self.NUM_JOINTS:
            raise ValueError(f"Expected {self.NUM_JOINTS} joint positions, got {len(target_positions)}")
        
        current_positions = self.getJointPositions(robot)
        num_steps = int(duration * steps_per_second)
        
        trajectory = []
        for step in range(num_steps + 1):
            # Smooth interpolation using cosine
            interpolation_factor = 0.5 * (1 - np.cos(np.pi * step / num_steps))
            waypoint = current_positions + interpolation_factor * (target_positions - current_positions)
            trajectory.append(waypoint)
        
        return trajectory
    
    def executeJointTrajectory(self, robot: RobotSide, trajectory: List[np.ndarray], 
                               timestep: float):
        """
        Execute a joint trajectory by setting waypoints.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            trajectory: List of joint position arrays
            timestep: Time between waypoints in seconds
        """
        for waypoint in trajectory:
            self.setJointPositions(robot, waypoint)
            yield timestep  # Yield control to allow simulation stepping

    # ==================== CARTESIAN/LINEAR MOTION ====================
    
    def getTcpPose(self, robot: RobotSide) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get TCP (Tool Center Point) position and orientation.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Tuple of (position [x, y, z], orientation as quaternion [w, x, y, z])
        """
        tcp_site_id = self.site_indices[robot].get("tcp")
        if tcp_site_id is None:
            raise ValueError(f"TCP site not found for {robot.value} robot")
        
        position = self.data.site_xpos[tcp_site_id].copy()
        orientation_matrix = self.data.site_xmat[tcp_site_id].reshape(3, 3)
        
        # Convert rotation matrix to quaternion
        quaternion = self._rotationMatrixToQuaternion(orientation_matrix)
        
        return position, quaternion
    
    def _rotationMatrixToQuaternion(self, rotation_matrix: np.ndarray) -> np.ndarray:
        """Convert 3x3 rotation matrix to quaternion [w, x, y, z]."""
        trace = np.trace(rotation_matrix)
        
        if trace > 0:
            scale = np.sqrt(trace + 1.0) * 2
            quaternion_w = 0.25 * scale
            quaternion_x = (rotation_matrix[2, 1] - rotation_matrix[1, 2]) / scale
            quaternion_y = (rotation_matrix[0, 2] - rotation_matrix[2, 0]) / scale
            quaternion_z = (rotation_matrix[1, 0] - rotation_matrix[0, 1]) / scale
        elif rotation_matrix[0, 0] > rotation_matrix[1, 1] and rotation_matrix[0, 0] > rotation_matrix[2, 2]:
            scale = np.sqrt(1.0 + rotation_matrix[0, 0] - rotation_matrix[1, 1] - rotation_matrix[2, 2]) * 2
            quaternion_w = (rotation_matrix[2, 1] - rotation_matrix[1, 2]) / scale
            quaternion_x = 0.25 * scale
            quaternion_y = (rotation_matrix[0, 1] + rotation_matrix[1, 0]) / scale
            quaternion_z = (rotation_matrix[0, 2] + rotation_matrix[2, 0]) / scale
        elif rotation_matrix[1, 1] > rotation_matrix[2, 2]:
            scale = np.sqrt(1.0 + rotation_matrix[1, 1] - rotation_matrix[0, 0] - rotation_matrix[2, 2]) * 2
            quaternion_w = (rotation_matrix[0, 2] - rotation_matrix[2, 0]) / scale
            quaternion_x = (rotation_matrix[0, 1] + rotation_matrix[1, 0]) / scale
            quaternion_y = 0.25 * scale
            quaternion_z = (rotation_matrix[1, 2] + rotation_matrix[2, 1]) / scale
        else:
            scale = np.sqrt(1.0 + rotation_matrix[2, 2] - rotation_matrix[0, 0] - rotation_matrix[1, 1]) * 2
            quaternion_w = (rotation_matrix[1, 0] - rotation_matrix[0, 1]) / scale
            quaternion_x = (rotation_matrix[0, 2] + rotation_matrix[2, 0]) / scale
            quaternion_y = (rotation_matrix[1, 2] + rotation_matrix[2, 1]) / scale
            quaternion_z = 0.25 * scale
        
        return np.array([quaternion_w, quaternion_x, quaternion_y, quaternion_z])
    
    def computeJacobian(self, robot: RobotSide) -> np.ndarray:
        """
        Compute the Jacobian matrix for the specified robot.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            6x6 Jacobian matrix (3 rows translation, 3 rows rotation)
        """
        tcp_site_id = self.site_indices[robot].get("tcp")
        if tcp_site_id is None:
            raise ValueError(f"TCP site not found for {robot.value} robot")
        
        # Get body ID from site
        body_id = self.model.site_bodyid[tcp_site_id]
        
        # Allocate Jacobian arrays
        jacobian_position = np.zeros((3, self.model.nv))
        jacobian_rotation = np.zeros((3, self.model.nv))
        
        # Compute Jacobian
        mujoco.mj_jacSite(self.model, self.data, jacobian_position, jacobian_rotation, tcp_site_id)
        
        # Extract columns corresponding to robot joints
        joint_columns = []
        for name in self.JOINT_NAMES:
            joint_id = self.joint_indices[robot].get(name)
            if joint_id is not None:
                dof_addr = self.model.jnt_dofadr[joint_id]
                joint_columns.append(dof_addr)
        
        jacobian_robot = np.vstack([
            jacobian_position[:, joint_columns],
            jacobian_rotation[:, joint_columns]
        ])
        
        return jacobian_robot
    
    def solveInverseKinematics(self, robot: RobotSide, target_position: np.ndarray,
                               target_orientation: Optional[np.ndarray] = None,
                               max_iterations: int = 100, tolerance: float = 1e-4) -> Optional[np.ndarray]:
        """
        Solve inverse kinematics using damped least squares.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            target_position: Target TCP position [x, y, z]
            target_orientation: Target TCP orientation as quaternion [w, x, y, z] (optional)
            max_iterations: Maximum IK iterations
            tolerance: Position error tolerance
            
        Returns:
            Joint positions achieving the target, or None if not found
        """
        # Store original positions
        original_ctrl = self.data.ctrl.copy()
        original_qpos = self.data.qpos.copy()
        
        damping = 0.1
        
        for iteration in range(max_iterations):
            mujoco.mj_forward(self.model, self.data)
            
            current_position, current_orientation = self.getTcpPose(robot)
            position_error = target_position - current_position
            
            if np.linalg.norm(position_error) < tolerance:
                joint_positions = self.getJointPositions(robot)
                # Restore original state
                self.data.ctrl[:] = original_ctrl
                self.data.qpos[:] = original_qpos
                mujoco.mj_forward(self.model, self.data)
                return joint_positions
            
            # Compute Jacobian (position only for now)
            jacobian = self.computeJacobian(robot)[:3, :]  # Only position rows
            
            # Damped least squares
            jacobian_transpose = jacobian.T
            lambda_squared = damping ** 2
            pseudo_inverse = jacobian_transpose @ np.linalg.inv(
                jacobian @ jacobian_transpose + lambda_squared * np.eye(3)
            )
            
            delta_joints = pseudo_inverse @ position_error
            
            # Update joint positions
            current_joints = self.getJointPositions(robot)
            new_joints = current_joints + delta_joints * 0.5  # Step size
            
            # Apply joint limits
            for idx, name in enumerate(self.JOINT_NAMES):
                joint_id = self.joint_indices[robot].get(name)
                if joint_id is not None:
                    lower_limit = self.model.jnt_range[joint_id, 0]
                    upper_limit = self.model.jnt_range[joint_id, 1]
                    new_joints[idx] = np.clip(new_joints[idx], lower_limit, upper_limit)
            
            self.setJointPositions(robot, new_joints)
            mujoco.mj_forward(self.model, self.data)
        
        # Restore original state
        self.data.ctrl[:] = original_ctrl
        self.data.qpos[:] = original_qpos
        mujoco.mj_forward(self.model, self.data)
        
        return None  # IK failed
    
    def moveLinear(self, robot: RobotSide, target_position: np.ndarray,
                   duration: float, steps_per_second: int = 100) -> List[np.ndarray]:
        """
        Generate trajectory for linear Cartesian motion.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            target_position: Target TCP position [x, y, z]
            duration: Motion duration in seconds
            steps_per_second: Trajectory resolution
            
        Returns:
            List of joint position waypoints for linear motion
        """
        current_position, _ = self.getTcpPose(robot)
        num_steps = int(duration * steps_per_second)
        
        trajectory = []
        
        for step in range(num_steps + 1):
            # Linear interpolation
            interpolation_factor = step / num_steps
            waypoint_position = current_position + interpolation_factor * (target_position - current_position)
            
            # Solve IK for this position
            joint_positions = self.solveInverseKinematics(robot, waypoint_position)
            
            if joint_positions is not None:
                trajectory.append(joint_positions)
            else:
                # If IK fails, use previous waypoint
                if trajectory:
                    trajectory.append(trajectory[-1].copy())
                else:
                    trajectory.append(self.getJointPositions(robot))
        
        return trajectory

    # ==================== UNIFIED/PARALLEL MOTION ====================
    
    def moveUnified(self, left_target: np.ndarray, right_target: np.ndarray,
                    duration: float, steps_per_second: int = 500) -> Tuple[List[np.ndarray], List[np.ndarray]]:
        """
        Generate synchronized trajectories for both robots.
        
        Both robots move simultaneously and complete motion at the same time.
        
        Args:
            left_target: Target joint positions for left robot
            right_target: Target joint positions for right robot
            duration: Motion duration in seconds
            steps_per_second: Trajectory resolution
            
        Returns:
            Tuple of (left_trajectory, right_trajectory)
        """
        left_trajectory = self.moveJoints(RobotSide.LEFT, left_target, duration, steps_per_second)
        right_trajectory = self.moveJoints(RobotSide.RIGHT, right_target, duration, steps_per_second)
        
        return left_trajectory, right_trajectory
    
    def setUnifiedJointPositions(self, left_positions: np.ndarray, right_positions: np.ndarray):
        """
        Set joint positions for both robots simultaneously.
        
        Args:
            left_positions: Joint positions for left robot
            right_positions: Joint positions for right robot
        """
        self.setJointPositions(RobotSide.LEFT, left_positions)
        self.setJointPositions(RobotSide.RIGHT, right_positions)
    
    def executeUnifiedTrajectory(self, left_trajectory: List[np.ndarray],
                                  right_trajectory: List[np.ndarray],
                                  timestep: float):
        """
        Execute synchronized trajectories for both robots.
        
        Args:
            left_trajectory: Waypoints for left robot
            right_trajectory: Waypoints for right robot
            timestep: Time between waypoints
        """
        num_waypoints = min(len(left_trajectory), len(right_trajectory))
        
        for idx in range(num_waypoints):
            self.setUnifiedJointPositions(left_trajectory[idx], right_trajectory[idx])
            yield timestep

    # ==================== GRIPPER CONTROL ====================
    
    def openGripper(self, robot: RobotSide):
        """
        Open the gripper fully.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
        """
        self.setGripperPosition(robot, self.GRIPPER_OPEN)
    
    def closeGripper(self, robot: RobotSide):
        """
        Close the gripper fully.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
        """
        self.setGripperPosition(robot, self.GRIPPER_CLOSED)
    
    def setGripperPosition(self, robot: RobotSide, position: float):
        """
        Set gripper to specific position.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            position: Gripper position (0 = open, 255 = closed)
        """
        position = np.clip(position, self.GRIPPER_OPEN, self.GRIPPER_CLOSED)
        gripper_id = self.actuator_indices[robot].get("gripper")
        if gripper_id is not None:
            self.data.ctrl[gripper_id] = position
    
    def getGripperPosition(self, robot: RobotSide) -> float:
        """
        Get current gripper position.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Gripper position (0 = open, 255 = closed)
        """
        gripper_id = self.actuator_indices[robot].get("gripper")
        if gripper_id is not None:
            return self.data.ctrl[gripper_id]
        return 0.0
    
    def openBothGrippers(self):
        """Open both grippers simultaneously."""
        self.openGripper(RobotSide.LEFT)
        self.openGripper(RobotSide.RIGHT)
    
    def closeBothGrippers(self):
        """Close both grippers simultaneously."""
        self.closeGripper(RobotSide.LEFT)
        self.closeGripper(RobotSide.RIGHT)

    # ==================== SENSOR READING ====================
    
    def getForceTorque(self, robot: RobotSide) -> np.ndarray:
        """
        Read force-torque sensor data.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Array of [fx, fy, fz, tx, ty, tz] - forces in N, torques in Nm
        """
        force_torque = np.zeros(6)
        
        force_sensor_id = self.sensor_indices[robot].get("fts_force")
        torque_sensor_id = self.sensor_indices[robot].get("fts_torque")
        
        if force_sensor_id is not None:
            force_addr = self.model.sensor_adr[force_sensor_id]
            force_dim = self.model.sensor_dim[force_sensor_id]
            force_torque[:3] = self.data.sensordata[force_addr:force_addr + force_dim]
        
        if torque_sensor_id is not None:
            torque_addr = self.model.sensor_adr[torque_sensor_id]
            torque_dim = self.model.sensor_dim[torque_sensor_id]
            force_torque[3:] = self.data.sensordata[torque_addr:torque_addr + torque_dim]
        
        return force_torque
    
    def getForce(self, robot: RobotSide) -> np.ndarray:
        """
        Get force reading only.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Array of [fx, fy, fz] in Newtons
        """
        return self.getForceTorque(robot)[:3]
    
    def getTorque(self, robot: RobotSide) -> np.ndarray:
        """
        Get torque reading only.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            Array of [tx, ty, tz] in Newton-meters
        """
        return self.getForceTorque(robot)[3:]

    # ==================== CAMERA CAPTURE ====================
    
    def getCameraImage(self, camera_name: str, width: int = 640, height: int = 480,
                       depth: bool = False) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """
        Capture image from specified camera.
        
        Args:
            camera_name: Name of camera (e.g., "left/wrist_cam", "right/wrist_cam", "overview")
            width: Image width in pixels
            height: Image height in pixels
            depth: If True, also return depth image
            
        Returns:
            RGB image array, or tuple of (RGB, depth) if depth=True
        """
        camera_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, camera_name)
        if camera_id < 0:
            raise ValueError(f"Camera '{camera_name}' not found")
        
        # Create renderer
        renderer = mujoco.Renderer(self.model, height, width)
        renderer.update_scene(self.data, camera=camera_name)
        
        # Render RGB
        rgb_image = renderer.render()
        
        if depth:
            # Enable depth rendering
            renderer.enable_depth_rendering(True)
            depth_image = renderer.render()
            renderer.enable_depth_rendering(False)
            renderer.close()
            return rgb_image, depth_image
        
        renderer.close()
        return rgb_image
    
    def getLeftWristCameraImage(self, width: int = 640, height: int = 480) -> np.ndarray:
        """Convenience method to get left wrist camera image."""
        return self.getCameraImage("left/wrist_cam", width, height)
    
    def getRightWristCameraImage(self, width: int = 640, height: int = 480) -> np.ndarray:
        """Convenience method to get right wrist camera image."""
        return self.getCameraImage("right/wrist_cam", width, height)

    # ==================== STATE QUERY ====================
    
    def getRobotState(self, robot: RobotSide) -> RobotState:
        """
        Get complete state of specified robot.
        
        Args:
            robot: RobotSide.LEFT or RobotSide.RIGHT
            
        Returns:
            RobotState dataclass with all state information
        """
        tcp_position, tcp_orientation = self.getTcpPose(robot)
        
        return RobotState(
            joint_positions=self.getJointPositions(robot),
            joint_velocities=self.getJointVelocities(robot),
            tcp_position=tcp_position,
            tcp_orientation=tcp_orientation,
            gripper_position=self.getGripperPosition(robot),
            force_torque=self.getForceTorque(robot)
        )
    
    def printRobotState(self, robot: RobotSide):
        """Print formatted robot state to console."""
        state = self.getRobotState(robot)
        print(f"\n{'='*50}")
        print(f"{robot.value.upper()} Robot State")
        print(f"{'='*50}")
        print(f"Joint Positions (rad): {np.round(state.joint_positions, 4)}")
        print(f"Joint Velocities (rad/s): {np.round(state.joint_velocities, 4)}")
        print(f"TCP Position (m): {np.round(state.tcp_position, 4)}")
        print(f"TCP Orientation (quat): {np.round(state.tcp_orientation, 4)}")
        print(f"Gripper Position: {state.gripper_position:.1f}")
        print(f"Force (N): {np.round(state.force_torque[:3], 4)}")
        print(f"Torque (Nm): {np.round(state.force_torque[3:], 4)}")
        print(f"{'='*50}\n")

    # ==================== UTILITY METHODS ====================
    
    def resetToHome(self):
        """Reset both robots to home configuration."""
        # Home configuration from keyframe
        home_left = np.array([-1.5708, -1.5708, 1.5708, -1.5708, -1.5708, 0])
        home_right = np.array([1.5708, -1.5708, 1.5708, -1.5708, 1.5708, 0])
        
        self.setJointPositions(RobotSide.LEFT, home_left)
        self.setJointPositions(RobotSide.RIGHT, home_right)
        
        # Set grippers to mid position
        self.setGripperPosition(RobotSide.LEFT, 127)
        self.setGripperPosition(RobotSide.RIGHT, 127)
