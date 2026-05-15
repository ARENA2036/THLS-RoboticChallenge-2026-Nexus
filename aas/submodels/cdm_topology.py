"""
Custom submodel: CDMTopology (urn:NEXUS:submodel:CDMTopology:1-0).

Encodes the full wire harness topology from the CDM:
  - Nodes  (board positions)
  - Segments (cable runs between nodes, with lengths, protection areas)
  - Connections (signal routing: wire occurrence → ordered segments → pin extremities)
  - Routings (explicit routing traces)

This submodel captures the information required to reproduce the full 2D
topology graph and is the complement to the BOM (which lists components).
"""

from typing import List, Optional

import basyx.aas.model as model

from ..semantic_ids import CDMTopology as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: Optional[str]) -> Optional[model.Property]:
    if value is None:
        return None
    return model.Property(id_short, value_type=str, value=value)


def _float_prop(id_short: str, value: Optional[float]) -> Optional[model.Property]:
    if value is None:
        return None
    return model.Property(id_short, value_type=float, value=value)


def _safe_id(raw: str) -> str:
    return raw.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# Node builder
# ---------------------------------------------------------------------------

def _build_node_smc(node) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        model.Property("NodeId", value_type=str, value=node.id),
        model.Property("CoordX", value_type=float, value=node.position.coord_x),
        model.Property("CoordY", value_type=float, value=node.position.coord_y),
        model.Property("CoordZ", value_type=float, value=node.position.coord_z),
    ]
    if node.label:
        elems.append(model.Property("Label", value_type=str, value=node.label))
    return model.SubmodelElementCollection(None, value=elems, semantic_id=_sem(SM_IDs.NODE))


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def _build_segment_smc(segment) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        model.Property("SegmentId", value_type=str, value=segment.id),
        model.Property("StartNodeId", value_type=str, value=segment.start_node.id),
        model.Property("EndNodeId", value_type=str, value=segment.end_node.id),
    ]
    if segment.label:
        elems.append(model.Property("Label", value_type=str, value=segment.label))
    if segment.length is not None:
        elems.append(model.Property("LengthMm", value_type=float, value=segment.length))
    if segment.physical_length is not None:
        elems.append(model.Property("PhysicalLengthMm", value_type=float, value=segment.physical_length))
    if segment.virtual_length is not None:
        elems.append(model.Property("VirtualLengthMm", value_type=float, value=segment.virtual_length))
    if segment.min_bend_radius_mm is not None:
        elems.append(model.Property("MinBendRadiusMm", value_type=float, value=segment.min_bend_radius_mm))

    # Center curve (Bezier)
    if segment.center_curve is not None:
        curve = segment.center_curve
        cp_smcs = []
        for cp in curve.control_points:
            cp_smcs.append(
                model.SubmodelElementCollection(
                    None,
                    value=[
                        model.Property("X", value_type=float, value=cp.coord_x),
                        model.Property("Y", value_type=float, value=cp.coord_y),
                        model.Property("Z", value_type=float, value=cp.coord_z),
                    ],
                )
            )
        curve_elems: list[model.SubmodelElement] = [
            model.Property("Degree", value_type=int, value=curve.degree),
            model.SubmodelElementList(
                "ControlPoints",
                type_value_list_element=model.SubmodelElementCollection,
                value=cp_smcs,
            ),
        ]
        elems.append(model.SubmodelElementCollection("CenterCurve", value=curve_elems))

    # Protection areas
    if segment.protection_areas:
        pa_smcs = []
        for pa in segment.protection_areas:
            pa_elems = [
                model.Property("StartLocation", value_type=float, value=pa.start_location),
                model.Property("EndLocation", value_type=float, value=pa.end_location),
                model.Property(
                    "ProtectionOccurrenceId",
                    value_type=str,
                    value=pa.wire_protection_occurrence.id,
                ),
                model.Property(
                    "ProtectionPartNumber",
                    value_type=str,
                    value=pa.wire_protection_occurrence.protection.part_number,
                ),
            ]
            pa_smcs.append(
                model.SubmodelElementCollection(
                    None, value=pa_elems, semantic_id=_sem(SM_IDs.PROTECTION_AREA)
                )
            )
        elems.append(
            model.SubmodelElementList(
                "ProtectionAreas",
                type_value_list_element=model.SubmodelElementCollection,
                value=pa_smcs,
            )
        )

    # Fixings on segment
    if segment.fixings:
        fixing_id_props = [
            model.Property(None, value_type=str, value=f.id)
            for f in segment.fixings
        ]
        elems.append(
            model.SubmodelElementList(
                "FixingIds",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=fixing_id_props,
            )
        )

    return model.SubmodelElementCollection(None, value=elems, semantic_id=_sem(SM_IDs.SEGMENT))


# ---------------------------------------------------------------------------
# Connection builder
# ---------------------------------------------------------------------------

def _build_connection_smc(connection) -> model.SubmodelElementCollection:
    wire_occ = connection.wire_occurrence
    wire_occ_id = wire_occ.id if hasattr(wire_occ, "id") else str(wire_occ)

    elems: list[model.SubmodelElement] = [
        model.Property("ConnectionId", value_type=str, value=connection.id),
        model.Property("WireOccurrenceId", value_type=str, value=wire_occ_id),
    ]
    if connection.signal_name:
        elems.append(model.Property("SignalName", value_type=str, value=connection.signal_name))

    # Ordered segment IDs
    if connection.segments:
        seg_id_props = [
            model.Property(None, value_type=str, value=seg.id)
            for seg in connection.segments
        ]
        elems.append(
            model.SubmodelElementList(
                "SegmentIds",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=seg_id_props,
            )
        )

    # Extremities
    if connection.extremities:
        ext_smcs = []
        for ext in connection.extremities:
            cp = ext.contact_point
            ext_elems = [
                model.Property("PositionOnWire", value_type=float, value=ext.position_on_wire),
                model.Property("ContactPointId", value_type=str, value=cp.id),
                model.Property("CavityId", value_type=str, value=cp.cavity.id),
                model.Property("CavityNumber", value_type=str, value=cp.cavity.cavity_number),
                model.Property("TerminalType", value_type=str, value=cp.terminal.terminal_type),
            ]
            ext_smcs.append(
                model.SubmodelElementCollection(
                    None, value=ext_elems, semantic_id=_sem(SM_IDs.EXTREMITY)
                )
            )
        elems.append(
            model.SubmodelElementList(
                "Extremities",
                type_value_list_element=model.SubmodelElementCollection,
                value=ext_smcs,
            )
        )

    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.CONNECTION)
    )


# ---------------------------------------------------------------------------
# Routing builder
# ---------------------------------------------------------------------------

def _build_routing_smc(routing) -> model.SubmodelElementCollection:
    elems: list[model.SubmodelElement] = [
        model.Property("ConnectionId", value_type=str, value=routing.routed_connection.id),
    ]
    if routing.id:
        elems.append(model.Property("RoutingId", value_type=str, value=routing.id))

    seg_id_props = [
        model.Property(None, value_type=str, value=seg.id)
        for seg in routing.segments
    ]
    if seg_id_props:
        elems.append(
            model.SubmodelElementList(
                "SegmentIds",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=seg_id_props,
            )
        )
    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.ROUTING)
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_cdm_topology(submodel_id: str, harness) -> model.Submodel:
    """Build a CDMTopology submodel from a CDM WireHarness.

    Args:
        submodel_id: The unique AAS submodel ID.
        harness: CDM WireHarness instance.

    Returns:
        A Submodel encoding the full topology (nodes, segments, connections, routings).
    """
    elements: list[model.SubmodelElement] = []

    # Nodes
    if harness.nodes:
        node_smcs = [_build_node_smc(n) for n in harness.nodes]
        elements.append(
            model.SubmodelElementList(
                "Nodes",
                type_value_list_element=model.SubmodelElementCollection,
                value=node_smcs,
            )
        )

    # Segments
    if harness.segments:
        seg_smcs = [_build_segment_smc(s) for s in harness.segments]
        elements.append(
            model.SubmodelElementList(
                "Segments",
                type_value_list_element=model.SubmodelElementCollection,
                value=seg_smcs,
            )
        )

    # Connections
    if harness.connections:
        conn_smcs = [_build_connection_smc(c) for c in harness.connections]
        elements.append(
            model.SubmodelElementList(
                "Connections",
                type_value_list_element=model.SubmodelElementCollection,
                value=conn_smcs,
            )
        )

    # Routings
    if harness.routings:
        routing_smcs = [_build_routing_smc(r) for r in harness.routings]
        elements.append(
            model.SubmodelElementList(
                "Routings",
                type_value_list_element=model.SubmodelElementCollection,
                value=routing_smcs,
            )
        )

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
