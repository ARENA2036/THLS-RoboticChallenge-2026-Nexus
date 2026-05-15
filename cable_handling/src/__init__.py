"""
Wire Harness Assembly Simulation Package

This package provides tools for simulating dual-robot wire harness
assembly tasks using MuJoCo.

Modules:
    robot_controller: DualRobotController class for robot control
    simulation: WireHarnessSimulation class for running simulations
"""

from .robot_controller import DualRobotController, RobotSide, RobotState
from .simulation import WireHarnessSimulation

__all__ = [
    "DualRobotController",
    "RobotSide",
    "RobotState",
    "WireHarnessSimulation",
]

__version__ = "0.1.0"
