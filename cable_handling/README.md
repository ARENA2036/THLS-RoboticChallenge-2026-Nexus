The **Cable Handling** module implements part of the **Skill** layer of the **Capability–Skill–Service (CSS)** methodology. It provides the concrete, executable implementation of robotic capabilities on specific resources, focusing on high-fidelity wire manipulation and dual-robot control.

This module serves as the low-level execution engine for the [Simulation](../simulation), providing the necessary force control and visual feedback interfaces for complex assembly tasks.

## Features

- **Dual UR10e Robots**: Two 6-DOF collaborative robots positioned facing each other
- **Robotiq 2F-85 Grippers**: Tendon-driven parallel jaw grippers with accurate dynamics
- **Force-Torque Sensors**: FTS300 sensors at each robot wrist for force control
- **Wrist Cameras**: Integrated cameras for visual feedback
- **Flexible Cable**: Composite cable element for wire harness simulation
- **Work Environment**: Table with connector fixtures and cable staging area

## Project Structure

```
cable_handling/
├── models/
│   ├── dual_ur10e_scene.xml      # Main simulation scene
│   ├── ur10e_with_gripper.xml    # Single robot assembly
│   ├── cable.xml                  # Cable definition
│   └── table_with_connectors.xml  # Work surface
├── src/
│   ├── __init__.py
│   ├── robot_controller.py        # Robot control interface
│   └── simulation.py              # Simulation runner
├── mujoco_menagerie/              # Robot model assets (submodule)
├── requirements.txt
└── README.md
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure mujoco_menagerie is available in the project directory (contains robot meshes). --> download

## Usage

### Running the Simulation

Basic simulation with viewer:
```bash
python src/simulation.py
```

With demo motion sequence:
```bash
python src/simulation.py --demo
```

Headless mode (no viewer):
```bash
python src/simulation.py --no-viewer --duration 10
```

### Python API

```python
from src import DualRobotController, RobotSide, WireHarnessSimulation

# Create simulation
sim = WireHarnessSimulation()

# Access controller
controller = sim.controller

# Joint motion
controller.setJointPositions(RobotSide.LEFT, [0, -1.57, 1.57, -1.57, -1.57, 0])

# Gripper control
controller.closeGripper(RobotSide.LEFT)
controller.openGripper(RobotSide.RIGHT)

# Read sensors
force_torque = controller.getForceTorque(RobotSide.LEFT)
tcp_position, tcp_orientation = controller.getTcpPose(RobotSide.LEFT)

# Get camera image
image = controller.getCameraImage("left/wrist_cam")

# Run simulation
sim.runWithViewer(duration=30)
```

## Robot Controller API

### Motion Control

| Method | Description |
|--------|-------------|
| `setJointPositions(robot, positions)` | Set target joint positions |
| `getJointPositions(robot)` | Get current joint positions |
| `moveJoints(robot, target, duration)` | Generate smooth joint trajectory |
| `moveLinear(robot, position, duration)` | Generate Cartesian linear trajectory |
| `moveUnified(left_target, right_target, duration)` | Synchronized dual-robot motion |

### Gripper Control

| Method | Description |
|--------|-------------|
| `openGripper(robot)` | Fully open gripper |
| `closeGripper(robot)` | Fully close gripper |
| `setGripperPosition(robot, value)` | Set position (0=open, 255=closed) |
| `openBothGrippers()` | Open both grippers |
| `closeBothGrippers()` | Close both grippers |

### Sensor Reading

| Method | Description |
|--------|-------------|
| `getForceTorque(robot)` | Get 6D force-torque [fx,fy,fz,tx,ty,tz] |
| `getForce(robot)` | Get force only [fx,fy,fz] |
| `getTorque(robot)` | Get torque only [tx,ty,tz] |
| `getTcpPose(robot)` | Get TCP position and orientation |

### Camera

| Method | Description |
|--------|-------------|
| `getCameraImage(camera_name, width, height)` | Capture camera image |
| `getLeftWristCameraImage()` | Capture from left wrist camera |
| `getRightWristCameraImage()` | Capture from right wrist camera |

## Actuator Indices

### Left Robot
- `left/shoulder_pan` (0)
- `left/shoulder_lift` (1)
- `left/elbow` (2)
- `left/wrist_1` (3)
- `left/wrist_2` (4)
- `left/wrist_3` (5)
- `left/gripper` (6)

### Right Robot
- `right/shoulder_pan` (7)
- `right/shoulder_lift` (8)
- `right/elbow` (9)
- `right/wrist_1` (10)
- `right/wrist_2` (11)
- `right/wrist_3` (12)
- `right/gripper` (13)

## Configuration

The simulation uses `implicitfast` integrator for stability. Key parameters can be modified in `dual_ur10e_scene.xml`:

- Timestep: `model.opt.timestep`
- Contact parameters: `<option cone="elliptic" impratio="10"/>`
- Gripper force range: `forcerange="-5 5"`

## License

This project uses models from mujoco_menagerie which have their own licenses. See individual model directories for details.

---
> [!TIP]
> Future extensions of this module aim to implement force-controlled or vision-guided connector insertion to handle real-world variance. Refer to Section VI of the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf).
