"""
Custom submodel: ExecutionTrace (urn:NEXUS:submodel:ExecutionTrace:1-0).

Records the outcome of a simulation execution run:
  - ExecutionSummary: overall success flag, wall-clock duration, step counts
  - StepOutcomes: per-step outcome (process type, success, timing, errors)
  - RobotTraces: per-robot sampled TCP path and error log

This submodel is populated *after* simulation execution completes.
The data types mirror simulation/interface/HardwareInterfaceModels.py.

For recording live robot data, pass sampled RobotFeedback as TcpWaypoints;
for error data, pass the list of RobotError objects logged during execution.
"""

from typing import List, Optional

import basyx.aas.model as model

from ..semantic_ids import ExecutionTrace as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: float) -> model.Property:
    return model.Property(id_short, value_type=float, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


def _bool_prop(id_short: str, value: bool) -> model.Property:
    return model.Property(id_short, value_type=bool, value=value)


# ---------------------------------------------------------------------------
# Data classes for the builder (not pydantic — kept simple)
# ---------------------------------------------------------------------------

class StepOutcome:
    """Outcome record for one ProcessStep execution."""
    def __init__(
        self,
        step_id: str,
        process_type: str,
        success: bool,
        start_time_s: float,
        end_time_s: float,
        executed_ticks: int = 0,
        errors: Optional[List] = None,
    ):
        self.step_id = step_id
        self.process_type = process_type
        self.success = success
        self.start_time_s = start_time_s
        self.end_time_s = end_time_s
        self.executed_ticks = executed_ticks
        self.errors = errors or []


class TcpWaypoint:
    """Single sampled TCP pose from RobotFeedback."""
    def __init__(
        self,
        timestamp_s: float,
        position_m: List[float],
        quat_wxyz: List[float],
    ):
        self.timestamp_s = timestamp_s
        self.position_m = position_m
        self.quat_wxyz = quat_wxyz


class RobotTrace:
    """Execution trace for one robot: sampled path + errors."""
    def __init__(
        self,
        robot_name: str,
        tcp_waypoints: Optional[List[TcpWaypoint]] = None,
        errors: Optional[List] = None,  # List[RobotError]
    ):
        self.robot_name = robot_name
        self.tcp_waypoints = tcp_waypoints or []
        self.errors = errors or []


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------

def _build_error_smc(error) -> model.SubmodelElementCollection:
    """Anonymous SMC for one RobotError."""
    return model.SubmodelElementCollection(
        None,
        value=[
            _str_prop("RobotName", error.robot_name),
            _float_prop("TimestampS", error.timestamp_s),
            _str_prop("ErrorCode", error.error_code),
            _str_prop("Message", error.message),
            _str_prop("Severity", str(error.severity)),
        ],
        semantic_id=_sem(SM_IDs.ROBOT_ERROR),
    )


def _build_step_outcome_smc(outcome: StepOutcome) -> model.SubmodelElementCollection:
    """Anonymous SMC for one StepOutcome."""
    elems = [
        _str_prop("StepId", outcome.step_id),
        _str_prop("ProcessType", outcome.process_type),
        _bool_prop("Success", outcome.success),
        _float_prop("StartTimeS", outcome.start_time_s),
        _float_prop("EndTimeS", outcome.end_time_s),
        _float_prop("DurationS", outcome.end_time_s - outcome.start_time_s),
        _int_prop("ExecutedTicks", outcome.executed_ticks),
    ]
    if outcome.errors:
        errors_sml = model.SubmodelElementList(
            "Errors",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_error_smc(e) for e in outcome.errors],
            semantic_id=_sem(SM_IDs.ROBOT_ERROR),
        )
        elems.append(errors_sml)
    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.STEP_OUTCOME)
    )


def _build_tcp_waypoint_smc(wp: TcpWaypoint) -> model.SubmodelElementCollection:
    """Anonymous SMC for one TcpWaypoint."""
    px, py, pz = wp.position_m[0], wp.position_m[1], wp.position_m[2]
    qw, qx, qy, qz = wp.quat_wxyz[0], wp.quat_wxyz[1], wp.quat_wxyz[2], wp.quat_wxyz[3]
    return model.SubmodelElementCollection(
        None,
        value=[
            _float_prop("TimestampS", wp.timestamp_s),
            model.SubmodelElementCollection("PositionM", value=[
                model.Property("X", value_type=float, value=px),
                model.Property("Y", value_type=float, value=py),
                model.Property("Z", value_type=float, value=pz),
            ]),
            model.SubmodelElementCollection("QuatWXYZ", value=[
                model.Property("W", value_type=float, value=qw),
                model.Property("X", value_type=float, value=qx),
                model.Property("Y", value_type=float, value=qy),
                model.Property("Z", value_type=float, value=qz),
            ]),
        ],
        semantic_id=_sem(SM_IDs.TCP_WAYPOINT),
    )


def _build_robot_trace_smc(trace: RobotTrace) -> model.SubmodelElementCollection:
    """Named SMC for one robot's execution trace."""
    safe_name = trace.robot_name.replace("-", "_").replace(" ", "_")
    elems: list[model.SubmodelElement] = [_str_prop("RobotName", trace.robot_name)]

    if trace.tcp_waypoints:
        waypoints_sml = model.SubmodelElementList(
            "TcpPath",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_tcp_waypoint_smc(wp) for wp in trace.tcp_waypoints],
            semantic_id=_sem(SM_IDs.TCP_WAYPOINT),
        )
        elems.append(waypoints_sml)

    if trace.errors:
        errors_sml = model.SubmodelElementList(
            "Errors",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_error_smc(e) for e in trace.errors],
            semantic_id=_sem(SM_IDs.ROBOT_ERROR),
        )
        elems.append(errors_sml)

    return model.SubmodelElementCollection(
        f"Robot_{safe_name}", value=elems, semantic_id=_sem(SM_IDs.ROBOT_TRACE)
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_execution_trace(
    submodel_id: str,
    *,
    production_id: str,
    overall_success: bool,
    total_steps: int,
    successful_steps: int,
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
    step_outcomes: Optional[List[StepOutcome]] = None,
    robot_traces: Optional[List[RobotTrace]] = None,
) -> model.Submodel:
    """Build an ExecutionTrace submodel from execution results.

    Args:
        submodel_id: Unique AAS submodel ID.
        production_id: Links this trace to a BillOfProcessAAS production ID.
        overall_success: True if all steps completed without fatal error.
        total_steps: Number of ProcessSteps scheduled.
        successful_steps: Number of ProcessSteps that completed successfully.
        start_time_s: Simulation clock at execution start.
        end_time_s: Simulation clock at execution end.
        step_outcomes: Per-step outcome records.
        robot_traces: Per-robot sampled TCP path and error log.

    Returns:
        Populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    # Summary
    elements.append(model.SubmodelElementCollection(
        "ExecutionSummary",
        value=[
            _str_prop("ProductionId", production_id),
            _bool_prop("OverallSuccess", overall_success),
            _int_prop("TotalSteps", total_steps),
            _int_prop("SuccessfulSteps", successful_steps),
            _int_prop("FailedSteps", total_steps - successful_steps),
            _float_prop("StartTimeS", start_time_s),
            _float_prop("EndTimeS", end_time_s),
            _float_prop("TotalDurationS", end_time_s - start_time_s),
        ],
    ))

    # Per-step outcomes
    if step_outcomes:
        outcomes_sml = model.SubmodelElementList(
            "StepOutcomes",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_step_outcome_smc(o) for o in step_outcomes],
            semantic_id=_sem(SM_IDs.STEP_OUTCOME),
        )
        elements.append(outcomes_sml)

    # Per-robot traces
    if robot_traces:
        robot_traces_smc = model.SubmodelElementCollection(
            "RobotTraces",
            value=[_build_robot_trace_smc(t) for t in robot_traces],
            semantic_id=_sem(SM_IDs.ROBOT_TRACE),
        )
        elements.append(robot_traces_smc)

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
