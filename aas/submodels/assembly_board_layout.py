"""
Custom submodel: AssemblyBoardLayout (urn:NEXUS:submodel:AssemblyBoardLayout:1-0).

Encodes the 2D board layout produced by LayoutGeneratorService:
  - BoardConfig: board dimensions and offsets in mm
  - LayoutMetrics: aggregate statistics (peg count, holder count, utilisation)
  - Pegs: list of PegPosition instances with board-coordinate position and metadata
  - ConnectorHolders: list of ConnectorHolderPosition instances

Built from layout_generator/LayoutModels.LayoutResponse.
"""

import basyx.aas.model as model

from ..semantic_ids import AssemblyBoardLayout as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: float) -> model.Property:
    return model.Property(id_short, value_type=float, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


def _point2d_smc(id_short: str | None, x: float, y: float) -> model.SubmodelElementCollection:
    return model.SubmodelElementCollection(
        id_short,
        value=[
            model.Property("X", value_type=float, value=x),
            model.Property("Y", value_type=float, value=y),
        ],
    )


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------

def _build_board_config_smc(board_config) -> model.SubmodelElementCollection:
    """Encode LayoutModels.BoardConfig into a named SMC."""
    elems = [
        _float_prop("WidthMm", board_config.width_mm),
        _float_prop("HeightMm", board_config.height_mm),
        _float_prop("OffsetX", board_config.offset_x),
        _float_prop("OffsetY", board_config.offset_y),
    ]
    return model.SubmodelElementCollection(
        "BoardConfig", value=elems, semantic_id=_sem(SM_IDs.BOARD_CONFIG)
    )


def _build_metrics_smc(metrics) -> model.SubmodelElementCollection:
    """Encode LayoutMetrics into a named SMC."""
    elems = [
        _int_prop("TotalPegs", metrics.total_pegs),
        _int_prop("TotalHolders", metrics.total_holders),
        _int_prop("MergedPositions", metrics.merged_positions),
        _int_prop("ShiftedPositions", metrics.shifted_positions),
        _float_prop("BoardUtilizationPercent", metrics.board_utilization_percent),
        _int_prop("BreakoutPegs", metrics.breakout_pegs),
        _int_prop("IntervalPegs", metrics.interval_pegs),
    ]
    return model.SubmodelElementCollection(
        "LayoutMetrics", value=elems, semantic_id=_sem(SM_IDs.LAYOUT_METRICS)
    )


def _build_peg_smc(peg) -> model.SubmodelElementCollection:
    """Encode one PegPosition as an anonymous SMC for use inside a SML."""
    elems = [
        _str_prop("PegId", peg.id),
        _point2d_smc("Position", peg.position.x, peg.position.y),
        _str_prop("SegmentId", peg.segment_id),
        _str_prop("Reason", peg.reason),
        _float_prop("OrientationDeg", peg.orientation_deg),
    ]
    if peg.merged_from is not None:
        elems.append(_str_prop("MergedFrom", peg.merged_from))
    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.PEG_POSITION)
    )


def _build_holder_smc(holder) -> model.SubmodelElementCollection:
    """Encode one ConnectorHolderPosition as an anonymous SMC."""
    elems = [
        _str_prop("ConnectorId", holder.connector_id),
        _point2d_smc("Position", holder.position.x, holder.position.y),
        _float_prop("OrientationDeg", holder.orientation_deg),
        _str_prop("HolderType", holder.holder_type),
        _float_prop("BufferRadiusMm", holder.buffer_radius_mm),
        _float_prop("WidthMm", holder.width_mm),
        _float_prop("HeightMm", holder.height_mm),
    ]
    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.CONNECTOR_HOLDER_POSITION)
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_assembly_board_layout(
    submodel_id: str,
    layout_response,
    board_config=None,
    harness_id: str = "",
) -> model.Submodel:
    """Build an AssemblyBoardLayout submodel from a LayoutResponse.

    Args:
        submodel_id: Unique AAS submodel ID (IRI or URN).
        layout_response: LayoutResponse from LayoutGeneratorService.generate_layout().
        board_config: Optional LayoutModels.BoardConfig for board dimensions.
        harness_id: Optional harness ID linking this layout to its WireHarness.

    Returns:
        Populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    if harness_id:
        elements.append(_str_prop("HarnessId", harness_id))

    if board_config is not None:
        elements.append(_build_board_config_smc(board_config))

    elements.append(_build_metrics_smc(layout_response.metrics))

    pegs_list = model.SubmodelElementList(
        "Pegs",
        type_value_list_element=model.SubmodelElementCollection,
        value=[_build_peg_smc(p) for p in layout_response.pegs],
        semantic_id=_sem(SM_IDs.PEG_POSITION),
    )
    elements.append(pegs_list)

    holders_list = model.SubmodelElementList(
        "ConnectorHolders",
        type_value_list_element=model.SubmodelElementCollection,
        value=[_build_holder_smc(h) for h in layout_response.connector_holders],
        semantic_id=_sem(SM_IDs.CONNECTOR_HOLDER_POSITION),
    )
    elements.append(holders_list)

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
