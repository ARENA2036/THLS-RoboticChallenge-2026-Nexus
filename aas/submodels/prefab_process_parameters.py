"""
Custom submodel: PreFabBillOfProcess (urn:NEXUS:submodel:PreFabBillOfProcess:1-0).

Encodes the upstream pre-fabrication process steps that produce the materials
delivered to the robotic assembly cell.  Process types follow OPC 40570
(Wire Harness Manufacturing):
  1. Cut  — trim each wire occurrence to its specified length
  2. Strip — remove insulation from both ends of each wire
  3. Crimp — attach terminals to stripped wire ends

Each phase is a SubmodelElementCollection; each step is an anonymous SMC
within a SubmodelElementList "Steps", following the same pattern as the
assembly BillOfProcessAAS.

Built from public.cdm.definitions.cdm_schema.WireHarness.
"""

from typing import Optional

import basyx.aas.model as model

from ..semantic_ids import PreFabBillOfProcess as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: float) -> model.Property:
    return model.Property(id_short, value_type=float, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


# ---------------------------------------------------------------------------
# Step-parameter SMC builders
# ---------------------------------------------------------------------------

def _cut_step_smc(
    wire_occurrence_id: str,
    sequence_number: int,
    cut_length_mm: Optional[float],
    wire_part_number: str,
    cross_section_mm2: Optional[float],
) -> model.SubmodelElementCollection:
    elems = [
        _int_prop("SequenceNumber", sequence_number),
        _str_prop("ProcessType", "Cut"),
        _str_prop("WireOccurrenceId", wire_occurrence_id),
        _str_prop("WirePartNumber", wire_part_number),
    ]
    if cut_length_mm is not None:
        elems.append(_float_prop("CutLengthMm", cut_length_mm))
    if cross_section_mm2 is not None:
        elems.append(_float_prop("CrossSectionMm2", cross_section_mm2))
    params = model.SubmodelElementCollection("Parameters", value=elems)
    return model.SubmodelElementCollection(
        None,
        value=[
            _str_prop("ProcessType", "Cut"),
            _str_prop("WireOccurrenceId", wire_occurrence_id),
            _int_prop("SequenceNumber", sequence_number),
            params,
        ],
        semantic_id=_sem(SM_IDs.OPC40570_CUT),
    )


def _strip_step_smc(
    wire_occurrence_id: str,
    extremity_index: int,
    sequence_number: int,
    strip_length_mm: float = 8.0,
    conductor_material: str = "copper",
) -> model.SubmodelElementCollection:
    params = model.SubmodelElementCollection(
        "Parameters",
        value=[
            _float_prop("StripLengthMm", strip_length_mm),
            _str_prop("ConductorMaterial", conductor_material),
        ],
    )
    return model.SubmodelElementCollection(
        None,
        value=[
            _str_prop("ProcessType", "Strip"),
            _str_prop("WireOccurrenceId", wire_occurrence_id),
            _int_prop("ExtremityIndex", extremity_index),
            _int_prop("SequenceNumber", sequence_number),
            params,
        ],
        semantic_id=_sem(SM_IDs.OPC40570_STRIP),
    )


def _crimp_step_smc(
    wire_occurrence_id: str,
    extremity_index: int,
    sequence_number: int,
    terminal_part_number: str,
    crimp_force_n: float = 0.0,
    cross_section_mm2: Optional[float] = None,
) -> model.SubmodelElementCollection:
    elems = [
        _str_prop("TerminalPartNumber", terminal_part_number),
        _float_prop("CrimpForceN", crimp_force_n),
    ]
    if cross_section_mm2 is not None:
        elems.append(_float_prop("CrossSectionMm2", cross_section_mm2))
    params = model.SubmodelElementCollection("Parameters", value=elems)
    return model.SubmodelElementCollection(
        None,
        value=[
            _str_prop("ProcessType", "Crimp"),
            _str_prop("WireOccurrenceId", wire_occurrence_id),
            _int_prop("ExtremityIndex", extremity_index),
            _int_prop("SequenceNumber", sequence_number),
            params,
        ],
        semantic_id=_sem(SM_IDs.OPC40570_CRIMP),
    )


# ---------------------------------------------------------------------------
# Helpers to extract wire data from CDM
# ---------------------------------------------------------------------------

def _get_wire_length_mm(wire_occurrence) -> Optional[float]:
    """Extract the first specified wire length in mm from a WireOccurrence."""
    definition = getattr(wire_occurrence, "wire", None)
    if definition is None:
        return None
    lengths = getattr(definition, "lengths", None) or []
    for wl in lengths:
        if wl.value_mm is not None:
            return float(wl.value_mm)
    return None


def _get_cross_section(wire_occurrence) -> Optional[float]:
    definition = getattr(wire_occurrence, "wire", None)
    if definition is None:
        return None
    return getattr(definition, "cross_section_area_mm2", None)


def _get_terminal_pn(harness, wire_occurrence, extremity_index: int) -> Optional[str]:
    """Find the terminal part number at a given extremity via CDM connections.

    CDM Connection structure:
      Connection.wire_occurrence → WireOccurrence
      Connection.extremities → List[Extremity]
        Extremity.position_on_wire: 0.0 = start (index 0), 1.0 = end (index 1)
        Extremity.contact_point → ContactPoint
          ContactPoint.terminal → Terminal definition (has part_number)
    """
    wo_id = wire_occurrence.id
    for conn in (harness.connections or []):
        conn_wo = getattr(conn, "wire_occurrence", None)
        if conn_wo is None or getattr(conn_wo, "id", None) != wo_id:
            continue
        extremities = getattr(conn, "extremities", []) or []
        # Sort by position_on_wire so index 0 = start, index 1 = end
        sorted_exts = sorted(extremities, key=lambda e: e.position_on_wire)
        if extremity_index < len(sorted_exts):
            cp = sorted_exts[extremity_index].contact_point
            terminal = getattr(cp, "terminal", None)
            if terminal:
                return getattr(terminal, "part_number", None)
    return None


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_prefab_process_parameters(
    submodel_id: str,
    harness,
    strip_length_mm: float = 8.0,
    default_crimp_force_n: float = 500.0,
) -> model.Submodel:
    """Build a PreFabBillOfProcess submodel from a WireHarness.

    Generates three phases (Cut → Strip → Crimp) with one step per
    wire occurrence (Cut), two steps per wire occurrence (Strip, one per end),
    and one step per terminal-connected extremity (Crimp).

    Args:
        submodel_id: Unique AAS submodel ID.
        harness: WireHarness instance from CDM.
        strip_length_mm: Default insulation strip length in mm.
        default_crimp_force_n: Default crimp force (N) when not derived from spec.

    Returns:
        Populated Submodel ready for serialization.
    """
    wire_occurrences = harness.wire_occurrences or []
    elements: list[model.SubmodelElement] = []

    elements.append(_str_prop("HarnessId", harness.id))
    elements.append(_str_prop("HarnessPartNumber", harness.part_number or ""))
    elements.append(_int_prop("TotalWireOccurrences", len(wire_occurrences)))

    # --- Phase 1: Cut ---
    cut_seq = 1
    cut_steps = []
    for wo in wire_occurrences:
        definition = getattr(wo, "wire", None)
        pn = getattr(definition, "part_number", wo.id) if definition else wo.id
        cut_steps.append(_cut_step_smc(
            wire_occurrence_id=wo.id,
            sequence_number=cut_seq,
            cut_length_mm=_get_wire_length_mm(wo),
            wire_part_number=pn,
            cross_section_mm2=_get_cross_section(wo),
        ))
        cut_seq += 1

    elements.append(model.SubmodelElementCollection(
        "CutPhase",
        value=[
            _str_prop("PhaseType", "PreFab_Cut"),
            _str_prop("Description", "Trim wire occurrences to specified lengths (OPC 40570 Cut)"),
            _int_prop("StepCount", len(cut_steps)),
            model.SubmodelElementList(
                "Steps",
                type_value_list_element=model.SubmodelElementCollection,
                value=cut_steps,
                semantic_id=_sem(SM_IDs.OPC40570_CUT),
            ),
        ],
    ))

    # --- Phase 2: Strip ---
    strip_seq = 1
    strip_steps = []
    for wo in wire_occurrences:
        definition = getattr(wo, "wire", None)
        conductor_mat = "copper"
        if definition:
            cm = getattr(definition, "conductor_material", None)
            if cm:
                conductor_mat = str(cm)
        for ext_idx in (0, 1):
            strip_steps.append(_strip_step_smc(
                wire_occurrence_id=wo.id,
                extremity_index=ext_idx,
                sequence_number=strip_seq,
                strip_length_mm=strip_length_mm,
                conductor_material=conductor_mat,
            ))
            strip_seq += 1

    elements.append(model.SubmodelElementCollection(
        "StripPhase",
        value=[
            _str_prop("PhaseType", "PreFab_Strip"),
            _str_prop("Description", "Remove insulation from both wire ends (OPC 40570 Strip)"),
            _int_prop("StepCount", len(strip_steps)),
            model.SubmodelElementList(
                "Steps",
                type_value_list_element=model.SubmodelElementCollection,
                value=strip_steps,
                semantic_id=_sem(SM_IDs.OPC40570_STRIP),
            ),
        ],
    ))

    # --- Phase 3: Crimp ---
    crimp_seq = 1
    crimp_steps = []
    for wo in wire_occurrences:
        for ext_idx in (0, 1):
            terminal_pn = _get_terminal_pn(harness, wo, ext_idx)
            if terminal_pn is None:
                continue
            crimp_steps.append(_crimp_step_smc(
                wire_occurrence_id=wo.id,
                extremity_index=ext_idx,
                sequence_number=crimp_seq,
                terminal_part_number=terminal_pn,
                crimp_force_n=default_crimp_force_n,
                cross_section_mm2=_get_cross_section(wo),
            ))
            crimp_seq += 1

    elements.append(model.SubmodelElementCollection(
        "CrimpPhase",
        value=[
            _str_prop("PhaseType", "PreFab_Crimp"),
            _str_prop("Description", "Attach terminals to stripped wire ends (OPC 40570 Crimp)"),
            _int_prop("StepCount", len(crimp_steps)),
            model.SubmodelElementList(
                "Steps",
                type_value_list_element=model.SubmodelElementCollection,
                value=crimp_steps,
                semantic_id=_sem(SM_IDs.OPC40570_CRIMP),
            ),
        ],
    ))

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
