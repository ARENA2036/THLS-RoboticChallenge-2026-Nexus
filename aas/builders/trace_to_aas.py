"""
Builder: Execution results → ExecutionTraceAAS.
"""

from typing import List, Optional

from ..shells.execution_trace_aas import (
    ExecutionTraceAASBundle,
    build_execution_trace_aas,
)
from ..submodels.execution_trace import StepOutcome, RobotTrace


def build_aas_from_trace(
    production_id: str,
    *,
    overall_success: bool,
    total_steps: int,
    successful_steps: int,
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
    step_outcomes: Optional[List[StepOutcome]] = None,
    robot_traces: Optional[List[RobotTrace]] = None,
    manufacturer_name: str = "NEXUS",
) -> ExecutionTraceAASBundle:
    """Build an ExecutionTraceAAS from simulation execution results.

    Args:
        production_id: Links this trace to a BillOfProcessAAS production ID.
        overall_success: True if all steps completed without fatal error.
        total_steps: Number of ProcessSteps scheduled.
        successful_steps: Number of ProcessSteps that completed successfully.
        start_time_s: Simulation clock at execution start.
        end_time_s: Simulation clock at execution end.
        step_outcomes: Per-step outcome records (StepOutcome instances).
        robot_traces: Per-robot sampled TCP path and error log (RobotTrace instances).
        manufacturer_name: Organisation that ran the simulation.

    Returns:
        ExecutionTraceAASBundle (shell + 2 submodels).
    """
    return build_execution_trace_aas(
        production_id,
        overall_success=overall_success,
        total_steps=total_steps,
        successful_steps=successful_steps,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        step_outcomes=step_outcomes,
        robot_traces=robot_traces,
        manufacturer_name=manufacturer_name,
    )
