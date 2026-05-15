"""
Custom submodel: MaterialDelivery (urn:NEXUS:submodel:MaterialDelivery:1-0).

Encodes all per-object and per-wire-end pickup positions used during the
board-setup and wire-routing simulation phases:
  - PickupParameters: global motion/gripper parameters
  - ObjectPickups: pegs and connector holders with 3-D pickup poses
  - WireEndPickups: per-wire-end pickup positions and crimp orientations
  - PullTestThresholds: cross-section → minimum pull-off force

Built from simulation/core/ConfigModels.BoardSetupConfig and WireRoutingConfig.
"""

from typing import Optional

import basyx.aas.model as model

from ..semantic_ids import MaterialDelivery as SM_IDs


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


def _vec3_smc(id_short: str | None, xyz) -> model.SubmodelElementCollection:
    return model.SubmodelElementCollection(
        id_short,
        value=[
            model.Property("X", value_type=float, value=float(xyz[0])),
            model.Property("Y", value_type=float, value=float(xyz[1])),
            model.Property("Z", value_type=float, value=float(xyz[2])),
        ],
    )


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------

def _build_board_setup_params_smc(board_setup_config) -> model.SubmodelElementCollection:
    """Global motion parameters for the board-setup phase."""
    elems = [
        _float_prop("ApproachOffsetM", board_setup_config.approach_offset_m),
        _float_prop("RetreatOffsetM", board_setup_config.retreat_offset_m),
        _float_prop("TransportHeightOffsetM", board_setup_config.transport_height_offset_m),
        _float_prop("PickupClearanceRadiusM", board_setup_config.pickup_clearance_radius_m),
        _float_prop("GripperOpenValue", board_setup_config.gripper_open_value),
        _float_prop("GripperCloseValue", board_setup_config.gripper_close_value),
        _float_prop("GripperSettleS", board_setup_config.gripper_settle_s),
    ]
    return model.SubmodelElementCollection(
        "BoardSetupParameters", value=elems, semantic_id=_sem(SM_IDs.PICKUP_PARAMETERS)
    )


def _build_wire_routing_params_smc(wire_routing_config) -> model.SubmodelElementCollection:
    """Global motion parameters for the wire-routing phase."""
    elems = [
        _float_prop("PegPassHeightOffsetM", wire_routing_config.peg_pass_height_offset_m),
        _float_prop("BetweenPegHeightOffsetM", wire_routing_config.between_peg_height_offset_m),
        _float_prop("InsertionPreAdjustmentM", wire_routing_config.insertion_pre_adjustment_m),
        _float_prop("RegraspRetractM", wire_routing_config.regrasp_retract_m),
        _float_prop("InsertionApproachDistanceM", wire_routing_config.insertion_approach_distance_m),
        _float_prop("PegSlotOffsetM", wire_routing_config.peg_slot_offset_m),
        _float_prop("PegClearanceM", wire_routing_config.peg_clearance_m),
        _float_prop("CableHangHeightM", wire_routing_config.cable_hang_height_m),
        _float_prop("GripperOpenValue", wire_routing_config.gripper_open_value),
        _float_prop("GripperCloseValue", wire_routing_config.gripper_close_value),
        _float_prop("GripperSettleS", wire_routing_config.gripper_settle_s),
    ]
    return model.SubmodelElementCollection(
        "WireRoutingParameters", value=elems, semantic_id=_sem(SM_IDs.PICKUP_PARAMETERS)
    )


def _build_object_pickup_smc(pickup) -> model.SubmodelElementCollection:
    """Anonymous SMC for one ObjectPickupConfig entry."""
    return model.SubmodelElementCollection(
        None,
        value=[
            _str_prop("ObjectId", pickup.object_id),
            _str_prop("ObjectType", pickup.object_type),
            _vec3_smc("PickupPositionM", pickup.pickup_position_m),
        ],
        semantic_id=_sem(SM_IDs.OBJECT_PICKUP),
    )


def _build_wire_end_pickup_smc(pickup) -> model.SubmodelElementCollection:
    """Anonymous SMC for one WireEndPickupConfig entry."""
    elems = [
        _str_prop("WireOccurrenceId", pickup.wire_occurrence_id),
        _int_prop("ExtremityIndex", pickup.extremity_index),
        _vec3_smc("PickupPositionM", pickup.pickup_position_m),
        _float_prop("CrimpOrientationDeg", pickup.crimp_orientation_deg),
        _float_prop("CableAxisOrientationDeg", pickup.cable_axis_orientation_deg),
    ]
    if pickup.anchor_position_m is not None:
        elems.append(_vec3_smc("AnchorPositionM", pickup.anchor_position_m))
    return model.SubmodelElementCollection(
        None, value=elems, semantic_id=_sem(SM_IDs.WIRE_END_PICKUP)
    )


def _build_pull_test_threshold_smc(threshold) -> model.SubmodelElementCollection:
    """Anonymous SMC for one PullTestThresholdConfig entry."""
    return model.SubmodelElementCollection(
        None,
        value=[
            _float_prop("MinCrossSectionMm2", threshold.min_cross_section_mm2),
            _float_prop("MaxCrossSectionMm2", threshold.max_cross_section_mm2),
            _float_prop("ThresholdForceN", threshold.threshold_force_n),
        ],
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_material_delivery(
    submodel_id: str,
    board_setup_config=None,
    wire_routing_config=None,
) -> model.Submodel:
    """Build a MaterialDelivery submodel from simulation config objects.

    Args:
        submodel_id: Unique AAS submodel ID.
        board_setup_config: Optional BoardSetupConfig (peg/holder pickup positions).
        wire_routing_config: Optional WireRoutingConfig (wire-end pickup positions).

    Returns:
        Populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    if board_setup_config is not None:
        elements.append(_build_board_setup_params_smc(board_setup_config))

        object_pickups = model.SubmodelElementList(
            "ObjectPickups",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_object_pickup_smc(p) for p in board_setup_config.pickup_positions],
            semantic_id=_sem(SM_IDs.OBJECT_PICKUP),
        )
        elements.append(object_pickups)

    if wire_routing_config is not None:
        elements.append(_build_wire_routing_params_smc(wire_routing_config))

        wire_end_pickups = model.SubmodelElementList(
            "WireEndPickups",
            type_value_list_element=model.SubmodelElementCollection,
            value=[_build_wire_end_pickup_smc(p) for p in wire_routing_config.wire_end_pickups],
            semantic_id=_sem(SM_IDs.WIRE_END_PICKUP),
        )
        elements.append(wire_end_pickups)

        if wire_routing_config.pull_test_thresholds:
            pull_tests = model.SubmodelElementList(
                "PullTestThresholds",
                type_value_list_element=model.SubmodelElementCollection,
                value=[_build_pull_test_threshold_smc(t)
                       for t in wire_routing_config.pull_test_thresholds],
            )
            elements.append(pull_tests)

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
