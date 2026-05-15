"""
ExecutionTraceAAS — Instance AAS for a completed simulation execution.

Carries two submodels:
  1. DigitalNameplate    (IDTA 02006-2-0)
  2. ExecutionTrace      (urn:NEXUS:submodel:ExecutionTrace:1-0)

GlobalAssetId convention:
    urn:NEXUS:trace:{production_id}
"""

from dataclasses import dataclass
from typing import List, Optional

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.execution_trace import (
    build_execution_trace,
    StepOutcome,
    RobotTrace,
)


@dataclass
class ExecutionTraceAASBundle:
    """A complete ExecutionTraceAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    trace_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.trace_submodel]


def build_execution_trace_aas(
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
    """Build a complete ExecutionTraceAAS from simulation execution results.

    Args:
        production_id: Links this trace to a BillOfProcessAAS production ID.
        overall_success: True if all steps completed without fatal error.
        total_steps: Number of ProcessSteps scheduled.
        successful_steps: Number of ProcessSteps that completed successfully.
        start_time_s: Simulation clock at execution start.
        end_time_s: Simulation clock at execution end.
        step_outcomes: Per-step outcome records.
        robot_traces: Per-robot sampled TCP path and error log.
        manufacturer_name: Organisation that ran the simulation.

    Returns:
        ExecutionTraceAASBundle with shell and two submodels.
    """
    safe_pid = production_id.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:trace:{safe_pid}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    trace_id = f"{global_asset_id}/submodel/ExecutionTrace"

    status = "SUCCESS" if overall_success else "FAILED"

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=production_id,
        manufacturer_product_designation=(
            f"Execution trace for production {production_id}: "
            f"{successful_steps}/{total_steps} steps {status}"
        ),
        manufacturer_product_family="ExecutionTrace",
        manufacturer_product_type="SimulationExecutionLog",
    )

    trace_sm = build_execution_trace(
        trace_id,
        production_id=production_id,
        overall_success=overall_success,
        total_steps=total_steps,
        successful_steps=successful_steps,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        step_outcomes=step_outcomes,
        robot_traces=robot_traces,
    )

    asset_info = model.AssetInformation(
        model.AssetKind.INSTANCE,
        global_asset_id=global_asset_id,
    )

    def _sm_ref(sm: model.Submodel) -> model.ModelReference:
        return model.ModelReference(
            (model.Key(model.KeyTypes.SUBMODEL, sm.id),),
            model.Submodel,
        )

    shell = model.AssetAdministrationShell(
        asset_information=asset_info,
        id_=f"{global_asset_id}/shell",
        submodel={_sm_ref(nameplate), _sm_ref(trace_sm)},
    )

    return ExecutionTraceAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        trace_submodel=trace_sm,
    )
