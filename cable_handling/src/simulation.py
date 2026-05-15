"""
Wire Harness Assembly Simulation Runner

This module provides the main simulation loop for the dual UR10e robot
wire harness assembly environment.

Usage:
    python simulation.py [--no-viewer] [--duration SECONDS]
"""

import mujoco
import mujoco.viewer
import numpy as np
import time
import argparse
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.robot_controller import DualRobotController, RobotSide
from src.model_loader import load_dual_robot_scene, get_model_paths


class WireHarnessSimulation:
    """
    Main simulation class for wire harness assembly.
    
    Manages the MuJoCo simulation, viewer, and robot controller.
    """
    
    def __init__(self, model_path: str = None):
        """
        Initialize the simulation.
        
        Args:
            model_path: Path to MJCF model file. If None, uses programmatic loading
                       with robot_assembly.xml attached twice with prefixes.
        """
        script_directory = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(script_directory, "..", "models")
        
        # Use programmatic model loading with prefixes
        scene_path, robot_path = get_model_paths(models_dir)
        print(f"Loading scene from: {scene_path}")
        print(f"Loading robot assembly from: {robot_path}")
        
        # Load model using MjSpec API with prefixes
        self.model = load_dual_robot_scene(scene_path, robot_path)
        self.data = mujoco.MjData(self.model)
        
        # Create robot controller
        self.controller = DualRobotController(self.model, self.data)
        
        # Simulation state
        self.running = False
        self.viewer = None
        self.simulation_time = 0.0
        
        # Apply home configuration
        self._applyHomeKeyframe()
        
        print("Simulation initialized successfully!")
        print(f"  - Timestep: {self.model.opt.timestep} s")
        print(f"  - Number of bodies: {self.model.nbody}")
        print(f"  - Number of joints: {self.model.njnt}")
        print(f"  - Number of actuators: {self.model.nu}")
        print(f"  - Number of sensors: {self.model.nsensor}")
    
    def _applyHomeKeyframe(self):
        """Apply the home keyframe configuration programmatically.
        
        Cable lies flat on table at z=0.77 (uses XML vertex positions).
        Connectors positioned at cable ends via weld constraints.
        Left gripper positioned above left connector, ready to grasp.
        """
        # Left robot: TCP at grasp position (0, -0.25, 0.78) - 1cm above connector
        # Top-down grasp: TCP z-axis points down, only 5.5° tilt from vertical
        # Wrist_3 at π/2 so gripper is perpendicular to cable
        left_home_joint_angles = [-2.2369, -1.2897, 2.168, -2.353, -1.5708, 1.5708]
        
        # Right robot: home position
        right_home_joint_angles = [1.57, -1.57, 1.57, -1.57, 1.57, 0]
        
        # Grippers: both open
        left_gripper_ctrl = 0
        right_gripper_ctrl = 0
        
        # Set robot arm joints
        for prefix, angles in [("left", left_home_joint_angles), ("right", right_home_joint_angles)]:
            joints = [f"{prefix}/shoulder_pan_joint", f"{prefix}/shoulder_lift_joint", 
                     f"{prefix}/elbow_joint", f"{prefix}/wrist_1_joint", 
                     f"{prefix}/wrist_2_joint", f"{prefix}/wrist_3_joint"]
            for joint_name, angle in zip(joints, angles):
                joint_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
                if joint_id >= 0:
                    self.data.qpos[self.model.jnt_qposadr[joint_id]] = angle
        
        # Set actuator controls
        for prefix, angles, gripper_ctrl in [("left", left_home_joint_angles, left_gripper_ctrl),
                                              ("right", right_home_joint_angles, right_gripper_ctrl)]:
            actuators = [f"{prefix}/shoulder_pan", f"{prefix}/shoulder_lift", f"{prefix}/elbow",
                        f"{prefix}/wrist_1", f"{prefix}/wrist_2", f"{prefix}/wrist_3", f"{prefix}/gripper"]
            ctrl_values = angles + [gripper_ctrl]
            for act_name, ctrl_val in zip(actuators, ctrl_values):
                act_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, act_name)
                if act_id >= 0:
                    self.data.ctrl[act_id] = ctrl_val
        
        # Position connectors at cable end positions (will be pulled by weld constraints)
        # The cable composite defines vertex positions, connectors should start there
        connector_positions = {
            "cable_end_left": [0.0, -0.25, 0.77],
            "cable_end_right": [0.0, 0.25, 0.77],
        }
        
        for body_name, position in connector_positions.items():
            body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, body_name)
            if body_id >= 0:
                for joint_idx in range(self.model.njnt):
                    if self.model.jnt_bodyid[joint_idx] == body_id:
                        if self.model.jnt_type[joint_idx] == mujoco.mjtJoint.mjJNT_FREE:
                            qpos_adr = self.model.jnt_qposadr[joint_idx]
                            self.data.qpos[qpos_adr:qpos_adr+3] = position
                            self.data.qpos[qpos_adr+3:qpos_adr+7] = [1, 0, 0, 0]
                        break
        
        # Zero velocities
        self.data.qvel[:] = 0
        mujoco.mj_forward(self.model, self.data)
        print("Applied home configuration - cable on table, gripper above connector")
    
    def step(self):
        """Perform one simulation step."""
        mujoco.mj_step(self.model, self.data)
        self.simulation_time = self.data.time
    
    def stepMultiple(self, num_steps: int):
        """Perform multiple simulation steps."""
        for _ in range(num_steps):
            self.step()
    
    def runWithViewer(self, duration: float = None, callback=None):
        """
        Run simulation with interactive viewer.
        
        Args:
            duration: Maximum simulation duration in seconds. None for unlimited.
            callback: Optional callback function called each step with (simulation, data)
        """
        self.running = True
        start_time = time.time()
        
        with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
            self.viewer = viewer
            
            print("\nSimulation running with viewer...")
            print("Press 'Q' in viewer window to quit")
            print("-" * 40)
            
            while viewer.is_running() and self.running:
                step_start = time.time()
                
                # Check duration limit
                if duration is not None:
                    if self.simulation_time >= duration:
                        print(f"\nReached duration limit: {duration}s")
                        break
                
                # Execute callback if provided
                if callback is not None:
                    callback(self, self.data)
                
                # Step simulation
                self.step()
                
                # Sync viewer
                viewer.sync()
                
                # Real-time synchronization
                elapsed_time = time.time() - step_start
                sleep_time = self.model.opt.timestep - elapsed_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            self.viewer = None
        
        self.running = False
        print(f"\nSimulation ended. Total time: {self.simulation_time:.2f}s")
    
    def runHeadless(self, duration: float, callback=None):
        """
        Run simulation without viewer (headless mode).
        
        Args:
            duration: Simulation duration in seconds
            callback: Optional callback function called each step
        """
        self.running = True
        print(f"\nRunning headless simulation for {duration}s...")
        
        while self.simulation_time < duration and self.running:
            if callback is not None:
                callback(self, self.data)
            
            self.step()
        
        self.running = False
        print(f"Headless simulation completed. Final time: {self.simulation_time:.2f}s")
    
    def stop(self):
        """Stop the simulation."""
        self.running = False
    
    def reset(self):
        """Reset simulation to initial state."""
        mujoco.mj_resetData(self.model, self.data)
        self._applyHomeKeyframe()
        self.simulation_time = 0.0
        print("Simulation reset to initial state")


def demoCallback(simulation: WireHarnessSimulation, data: mujoco.MjData):
    """
    Demo callback that performs cable handling demonstration.
    
    Gripper starts above left connector, lowers to grasp, lifts and moves cable.
    """
    controller = simulation.controller
    current_time = simulation.simulation_time
    
    # Demo sequence timing
    phase_duration = 2.0
    
    # All positions: Top-down grasp (TCP z-axis points down)
    # Grasp position: TCP at (0, -0.25, 0.78) - 1cm above connector, 5.5° tilt
    grasp_angles = np.array([-2.2369, -1.2897, 2.168, -2.353, -1.5708, 1.5708])
    # Lifted position: TCP at (0, -0.25, 0.95), 7.3° tilt
    lift_angles = np.array([-2.2366, -1.5726, 2.1723, -2.2982, -1.5708, 1.5708])
    # Moved sideways: TCP at (0.12, -0.18, 0.95), 11.2° tilt
    moved_angles = np.array([-2.053, -1.4403, 2.0525, -2.3781, -1.5708, 1.5708])
    
    # Phase 0: Wait at start position, gripper OPEN (0-2s)
    if current_time < phase_duration:
        if abs(current_time) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Waiting with gripper open...")
        controller.setJointPositions(RobotSide.LEFT, grasp_angles)
        controller.openGripper(RobotSide.LEFT)
    
    # Phase 1: Close gripper to grasp (2-4s)
    elif current_time < 2 * phase_duration:
        if abs(current_time - phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Grasping connector...")
        controller.setJointPositions(RobotSide.LEFT, grasp_angles)
        controller.closeGripper(RobotSide.LEFT)
    
    # Phase 2: Lift cable (4-6s)
    elif current_time < 3 * phase_duration:
        if abs(current_time - 2 * phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Lifting cable...")
        controller.setJointPositions(RobotSide.LEFT, lift_angles)
        controller.closeGripper(RobotSide.LEFT)
    
    # Phase 3: Move sideways (6-8s)
    elif current_time < 4 * phase_duration:
        if abs(current_time - 3 * phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Moving sideways...")
        controller.setJointPositions(RobotSide.LEFT, moved_angles)
        controller.closeGripper(RobotSide.LEFT)
    
    # Phase 4: Move back (8-10s)
    elif current_time < 5 * phase_duration:
        if abs(current_time - 4 * phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Moving back...")
        controller.setJointPositions(RobotSide.LEFT, lift_angles)
        controller.closeGripper(RobotSide.LEFT)
    
    # Phase 5: Lower (10-12s)
    elif current_time < 6 * phase_duration:
        if abs(current_time - 5 * phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Lowering...")
        controller.setJointPositions(RobotSide.LEFT, grasp_angles)
        controller.closeGripper(RobotSide.LEFT)
    
    # Phase 6: Release (12-14s)
    elif current_time < 7 * phase_duration:
        if abs(current_time - 6 * phase_duration) < simulation.model.opt.timestep:
            print(f"[{current_time:.1f}s] Releasing...")
        controller.openGripper(RobotSide.LEFT)
    
    # Idle
    else:
        controller.openGripper(RobotSide.LEFT)


def main():
    """Main entry point for simulation."""
    parser = argparse.ArgumentParser(description="Wire Harness Assembly Simulation")
    parser.add_argument("--no-viewer", action="store_true", 
                        help="Run without viewer (headless mode)")
    parser.add_argument("--duration", type=float, default=300.0,
                        help="Simulation duration in seconds (default: 30)")
    parser.add_argument("--model", type=str, default=None,
                        help="Path to MJCF model file")
    parser.add_argument("--demo", action="store_true",
                        help="Run demo motion sequence")
    
    args = parser.parse_args()
    
    try:
        # Create simulation
        simulation = WireHarnessSimulation(args.model)
        
        # Print initial state
        print("\nInitial robot states:")
        simulation.controller.printRobotState(RobotSide.LEFT)
        simulation.controller.printRobotState(RobotSide.RIGHT)
        
        # Select callback
        callback = demoCallback if args.demo else None
        
        # Run simulation
        if args.no_viewer:
            simulation.runHeadless(args.duration, callback=callback)
        else:
            simulation.runWithViewer(duration=args.duration, callback=callback)
        
        # Print final state
        print("\nFinal robot states:")
        simulation.controller.printRobotState(RobotSide.LEFT)
        simulation.controller.printRobotState(RobotSide.RIGHT)
        
    except FileNotFoundError as error:
        print(f"Error: {error}")
        print("\nMake sure the model file exists and the path is correct.")
        sys.exit(1)
    except Exception as error:
        print(f"Error during simulation: {error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
