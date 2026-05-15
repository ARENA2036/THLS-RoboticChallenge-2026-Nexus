# 🤖 Robotic Simulation (MuJoCo)

The **Simulation** module provides the verification environment for the assembly pipeline. It implements a high-fidelity **MuJoCo** simulation where dual robotic arms execute the generated [Bill of Process (BoP)](../bill_of_process) in a coordinated workcell.

## 🌟 Overview

As described in **Section V-B: Simulation-Based Realization** of the ETFA 2026 paper, this environment validates the end-to-end feasibility of the AI-driven planning pipeline.

### Key Features:
- **Dual-Arm Workcell**: Features two **UR10e** collaborative robots positioned on opposite sides of a 1200x800mm assembly board.
- **Precision Gripping**: Equipped with **Robotiq 2F-85** two-finger grippers for handling pegs, holders, and wires.
- **Advanced Kinematics**: Utilizes the **Pinocchio** library and a damped-least-squares inverse kinematics solver for smooth, collision-aware motion.
- **Workspace Coordination**: A zone-based coordinator prevents inter-arm conflicts and optimizes parallel execution (reaching 84% dual-arm utilization).
- **Physics-Based Verification**: Models complex interactions, including cable routing and insertion, with high physical accuracy.

## 🏗️ Architecture

- `core/`: Scene building, coordinate transformations, and configuration loading.
- `backend/`: MuJoCo physics engine interface and step-execution logic.
- `planning/`: Motion planning and dual-arm coordination algorithms.
- `models/`: URDF and MJCF models for robots, grippers, and workcell components.
- `visualization/`: Real-time rendering and video export utilities.

## 🚀 Usage

The simulation can be initialized with an [AssemblyStationAAS](../aas) and a [BillOfProcessAAS](../aas).

```bash
# Install dependencies
pip install -r simulation/requirements.txt

# Run a sample assembly video render
python3 simulation/examples/render_assembly_video.py
```

---
> [!TIP]
> The simulation environment supports real-time updates from the **BoardLayoutAAS**, allowing it to adapt to any harness variant without manual reconfiguration. Refer to Figure 6 in the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf) for a sequence of the board setup phase.
