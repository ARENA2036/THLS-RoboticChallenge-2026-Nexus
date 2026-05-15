"""
Planner client that delegates to a pluggable planning transport.

The transport protocol defines plan_movej and plan_movel.
Use PinocchioCartesianTransport for Pinocchio-based IK planning.
"""

from __future__ import annotations

from typing import List, Protocol, Tuple

from simulation.planning.PlanningModels import (
    MoveJRequest,
    MoveLRequest,
    MotionType,
    PlanningError,
    PlanningResult,
)


class PlanningTransport(Protocol):
    def plan_movej(self, request_data: MoveJRequest) -> PlanningResult:
        ...

    def plan_movel(self, request_data: MoveLRequest) -> PlanningResult:
        ...

    def compute_tcp_position(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        ...


class PlannerClient:
    def __init__(self, planning_transport: PlanningTransport) -> None:
        self.planning_transport = planning_transport

    def plan_movej(self, request_data: MoveJRequest) -> PlanningResult:
        return self.planning_transport.plan_movej(request_data)

    def plan_movel(self, request_data: MoveLRequest) -> PlanningResult:
        return self.planning_transport.plan_movel(request_data)

    def compute_tcp_position(self, joint_angles: List[float]) -> Tuple[float, float, float]:
        return self.planning_transport.compute_tcp_position(joint_angles)
