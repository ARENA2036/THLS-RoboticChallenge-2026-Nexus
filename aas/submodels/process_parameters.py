"""
IDTA 02031-1-0 — Process Parameters Type.

Maps a ProductionBillOfProcess onto the AAS Process Parameters submodel.

Structure:
  Submodel (ProcessParametersType)
  └── SMC "ProductionId"         — production batch metadata
  └── SMC "BOARD_SETUP"          — phase (one per PhaseType)
      └── SubmodelElementList "Steps"
          └── SMC (None)         — one per ProcessStep
              ├── Property "StepId"
              ├── Property "ProcessType"
              ├── Property "HarnessId"
              ├── Property "StationId"
              ├── Property "SequenceNumber"
              ├── Property "Description"
              ├── Property "EstimatedDurationS"   (optional)
              ├── SubmodelElementList "DependsOn" (optional)
              └── SMC "Parameters"               — typed per ProcessType

The Parameters SMC carries typed properties for each of the six ProcessType variants.

Spec: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Process%20Parameters%20Type
"""

from typing import List, Optional

import basyx.aas.model as model

from ..semantic_ids import ProcessParametersType as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str, sem_iri: Optional[str] = None) -> model.Property:
    kw = {"semantic_id": _sem(sem_iri)} if sem_iri else {}
    return model.Property(id_short, value_type=str, value=value, **kw)


def _int_prop(id_short: str, value: int, sem_iri: Optional[str] = None) -> model.Property:
    kw = {"semantic_id": _sem(sem_iri)} if sem_iri else {}
    return model.Property(id_short, value_type=int, value=value, **kw)


def _float_prop(id_short: str, value: float, sem_iri: Optional[str] = None) -> model.Property:
    kw = {"semantic_id": _sem(sem_iri)} if sem_iri else {}
    return model.Property(id_short, value_type=float, value=value, **kw)


# ---------------------------------------------------------------------------
# Parameter SMC builders — one per ProcessType variant
# ---------------------------------------------------------------------------

def _params_place_peg(params) -> model.SubmodelElementCollection:
    elems = [
        _str_prop("PegId", params.peg_id),
        _float_prop("PositionXMm", params.position_x_mm),
        _float_prop("PositionYMm", params.position_y_mm),
        _float_prop("OrientationDeg", params.orientation_deg),
        _str_prop("SegmentId", params.segment_id),
        _str_prop("PlacementReason", params.placement_reason),
    ]
    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


def _params_place_connector_holder(params) -> model.SubmodelElementCollection:
    elems = [
        _str_prop("ConnectorOccurrenceId", params.connector_occurrence_id),
        _float_prop("PositionXMm", params.position_x_mm),
        _float_prop("PositionYMm", params.position_y_mm),
        _float_prop("OrientationDeg", params.orientation_deg),
        _str_prop("HolderType", params.holder_type),
        _float_prop("WidthMm", params.width_mm),
        _float_prop("HeightMm", params.height_mm),
        _float_prop("BufferRadiusMm", params.buffer_radius_mm),
    ]
    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


def _params_route_wire(params) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        _str_prop("ConnectionId", params.connection_id),
        _str_prop("WireOccurrenceId", params.wire_occurrence_id),
        _str_prop("WirePartNumber", params.wire_part_number),
    ]

    # Ordered segment IDs
    seg_id_props = [
        model.Property(None, value_type=str, value=sid)
        for sid in params.ordered_segment_ids
    ]
    if seg_id_props:
        elems.append(
            model.SubmodelElementList(
                "OrderedSegmentIds",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=seg_id_props,
            )
        )

    # Ordered peg IDs
    peg_id_props = [
        model.Property(None, value_type=str, value=pid)
        for pid in params.ordered_peg_ids
    ]
    if peg_id_props:
        elems.append(
            model.SubmodelElementList(
                "OrderedPegIds",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=peg_id_props,
            )
        )

    # Extremities
    ext_smcs = []
    for ext in params.extremities:
        ext_elems = [
            _str_prop("ConnectorOccurrenceId", ext.connector_occurrence_id),
            _str_prop("ContactPointId", ext.contact_point_id),
            _str_prop("CavityId", ext.cavity_id),
            _str_prop("CavityNumber", ext.cavity_number),
            _str_prop("TerminalType", ext.terminal_type),
        ]
        ext_smcs.append(model.SubmodelElementCollection(None, value=ext_elems))
    if ext_smcs:
        elems.append(
            model.SubmodelElementList(
                "Extremities",
                type_value_list_element=model.SubmodelElementCollection,
                value=ext_smcs,
            )
        )

    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


def _params_apply_wire_protection(params) -> model.SubmodelElementCollection:
    elems = [
        _str_prop("WireProtectionOccurrenceId", params.wire_protection_occurrence_id),
        _str_prop("SegmentId", params.segment_id),
        _float_prop("StartLocation", params.start_location),
        _float_prop("EndLocation", params.end_location),
        _str_prop("ProtectionType", params.protection_type),
        _str_prop("PartNumber", params.part_number),
    ]
    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


def _params_apply_fixing(params) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        _str_prop("FixingOccurrenceId", params.fixing_occurrence_id),
        _str_prop("FixingType", params.fixing_type),
        _str_prop("PartNumber", params.part_number),
    ]
    if params.segment_id is not None:
        elems.append(_str_prop("SegmentId", params.segment_id))
    if params.position_on_segment is not None:
        elems.append(_float_prop("PositionOnSegment", params.position_on_segment))
    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


def _params_remove_harness(params) -> model.SubmodelElementCollection:
    elems = [_str_prop("HarnessId", params.harness_id)]
    return model.SubmodelElementCollection(
        "Parameters", value=elems, semantic_id=_sem(SM_IDs.PROCESS_PARAMETERS)
    )


# Dispatch table: parameter_type string → builder function
_PARAMS_BUILDERS = {
    "PLACE_PEG": _params_place_peg,
    "PLACE_CONNECTOR_HOLDER": _params_place_connector_holder,
    "ROUTE_WIRE": _params_route_wire,
    "APPLY_WIRE_PROTECTION": _params_apply_wire_protection,
    "APPLY_FIXING": _params_apply_fixing,
    "REMOVE_HARNESS": _params_remove_harness,
}


# ---------------------------------------------------------------------------
# ProcessStep SMC builder
# ---------------------------------------------------------------------------

def _build_step_smc(step) -> model.SubmodelElementCollection:
    """Build an anonymous SMC for one ProcessStep (for use inside a SML)."""
    elems: list[model.SubmodelElement] = [
        _str_prop("StepId", step.step_id, SM_IDs.PROCESS_STEP),
        _int_prop("SequenceNumber", step.sequence_number, SM_IDs.SEQUENCE_NUMBER),
        _str_prop("ProcessType", step.process_type.value, SM_IDs.PROCESS_TYPE),
        _str_prop("HarnessId", step.harness_id, SM_IDs.HARNESS_ID),
        _str_prop("StationId", step.station_id, SM_IDs.STATION_ID),
        _str_prop("Description", step.description),
    ]

    if step.estimated_duration_s is not None:
        elems.append(
            _float_prop("EstimatedDurationS", step.estimated_duration_s, SM_IDs.ESTIMATED_DURATION)
        )

    if step.depends_on:
        dep_props = [
            model.Property(None, value_type=str, value=dep_id)
            for dep_id in step.depends_on
        ]
        elems.append(
            model.SubmodelElementList(
                "DependsOn",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=dep_props,
                semantic_id=_sem(SM_IDs.DEPENDS_ON),
            )
        )

    # Typed parameters SMC
    param_type = step.parameters.parameter_type
    builder_fn = _PARAMS_BUILDERS.get(param_type)
    if builder_fn is not None:
        elems.append(builder_fn(step.parameters))

    return model.SubmodelElementCollection(None, value=elems)


# ---------------------------------------------------------------------------
# Phase SMC builder
# ---------------------------------------------------------------------------

def _build_phase_smc(phase) -> model.SubmodelElementCollection:
    """Build a named SMC for one AssemblyPhase."""
    elems: list[model.SubmodelElement] = [
        _str_prop("PhaseType", phase.phase_type.value, SM_IDs.ASSEMBLY_PHASE),
        _str_prop("PhaseLabel", phase.phase_label),
    ]

    if phase.steps:
        step_smcs = [_build_step_smc(step) for step in phase.steps]
        elems.append(
            model.SubmodelElementList(
                "Steps",
                type_value_list_element=model.SubmodelElementCollection,
                value=step_smcs,
            )
        )
    else:
        # Placeholder for empty phases (e.g., ConnectorAssembly v1)
        elems.append(_str_prop("Note", "No steps in this phase (placeholder)"))

    # Use phase_type as idShort (guaranteed unique within BoP)
    return model.SubmodelElementCollection(
        phase.phase_type.value,
        value=elems,
        semantic_id=_sem(SM_IDs.ASSEMBLY_PHASE),
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_process_parameters(
    submodel_id: str,
    bill_of_process,
) -> model.Submodel:
    """Build a ProcessParametersType submodel (IDTA 02031-1-0).

    Args:
        submodel_id: The unique AAS submodel ID.
        bill_of_process: ProductionBillOfProcess instance from bill_of_process/BoPModels.py.

    Returns:
        A Submodel with one SMC per assembly phase, each containing a
        SubmodelElementList of typed process step SMCs.
    """
    elements: list[model.SubmodelElement] = [
        # Batch metadata
        _str_prop("ProductionId", bill_of_process.production_id),
        _str_prop("CreatedAt", bill_of_process.created_at.isoformat()),
    ]

    # Harness references
    harness_ref_smcs = []
    for ref in bill_of_process.harness_refs:
        ref_elems: list[model.SubmodelElement] = [
            _str_prop("HarnessId", ref.harness_id),
            _str_prop("HarnessPartNumber", ref.harness_part_number),
            _str_prop("StationId", ref.station_id),
        ]
        if ref.cdm_source:
            ref_elems.append(_str_prop("CdmSource", ref.cdm_source))
        if ref.layout_source:
            ref_elems.append(_str_prop("LayoutSource", ref.layout_source))
        harness_ref_smcs.append(model.SubmodelElementCollection(None, value=ref_elems))

    if harness_ref_smcs:
        elements.append(
            model.SubmodelElementList(
                "HarnessRefs",
                type_value_list_element=model.SubmodelElementCollection,
                value=harness_ref_smcs,
            )
        )

    # Phases
    for phase in bill_of_process.phases:
        elements.append(_build_phase_smc(phase))

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
