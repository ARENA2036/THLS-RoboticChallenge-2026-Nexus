"""
IDTA 02020-1-0 — Capability Description.

Models the six process capabilities of the robotic assembly station, one per
BoP ProcessType.  Follows the CSS pattern: CapabilitySet > Capability >
CapabilityProperty list.

Each capability is modelled as a basyx.aas.model.Capability element (the AAS
metamodel's dedicated type) wrapped in a SubmodelElementCollection that also
holds typed CapabilityProperty constraints derived from the workcell config.

Spec: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Capability%20Description
"""

from typing import List, Optional, Tuple

import basyx.aas.model as model

from ..semantic_ids import CapabilityDescription as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _cap_prop(
    name: str,
    value: str,
    condition: str = SM_IDs.CONDITION_REQUIRED,
) -> model.SubmodelElementCollection:
    """Build a CapabilityProperty triple (name / value / condition)."""
    return model.SubmodelElementCollection(
        None,
        value=[
            model.Property(
                "PropertyName",
                value_type=str,
                value=name,
                semantic_id=_sem(SM_IDs.PROPERTY_NAME),
            ),
            model.Property(
                "PropertyValue",
                value_type=str,
                value=value,
                semantic_id=_sem(SM_IDs.PROPERTY_VALUE),
            ),
            model.Property(
                "PropertyCondition",
                value_type=str,
                value=condition,
                semantic_id=_sem(SM_IDs.PROPERTY_CONDITION),
            ),
        ],
        semantic_id=_sem(SM_IDs.CAPABILITY_PROPERTY),
    )


def _capability_smc(
    name: str,
    description: str,
    properties: List[model.SubmodelElementCollection],
) -> model.SubmodelElementCollection:
    """Build a Capability SMC with embedded capability element and properties."""
    inner: list[model.SubmodelElement] = [
        model.Capability(
            "Capability",
            semantic_id=_sem(SM_IDs.CAPABILITY),
        ),
        model.Property(
            "Description",
            value_type=str,
            value=description,
        ),
    ]
    if properties:
        inner.append(
            model.SubmodelElementList(
                "CapabilityProperties",
                type_value_list_element=model.SubmodelElementCollection,
                value=properties,
                semantic_id=_sem(SM_IDs.CAPABILITY_PROPERTY),
            )
        )
    return model.SubmodelElementCollection(
        name,
        value=inner,
        semantic_id=_sem(SM_IDs.CAPABILITY),
    )


# ---------------------------------------------------------------------------
# Individual capability builders
# ---------------------------------------------------------------------------

def _place_peg_capability(board_config) -> model.SubmodelElementCollection:
    props = [
        _cap_prop("PegShapeTypes", "fork_standard,round_pin,t_peg"),
        _cap_prop("BoardLengthM", str(board_config.length_m)),
        _cap_prop("BoardWidthM", str(board_config.width_m)),
        _cap_prop("PositionResolutionMm", "1.0"),
    ]
    return _capability_smc(
        "PlacePeg",
        "Place a wire-support peg at a specified (x,y) position and orientation on the assembly board.",
        props,
    )


def _place_connector_holder_capability(board_config) -> model.SubmodelElementCollection:
    props = [
        _cap_prop("HolderTypes", "SMALL,MEDIUM,LARGE"),
        _cap_prop("BoardLengthM", str(board_config.length_m)),
        _cap_prop("BoardWidthM", str(board_config.width_m)),
        _cap_prop("MinHolderWidthMm", "0.0"),
        _cap_prop("MaxHolderWidthMm", "200.0"),
    ]
    return _capability_smc(
        "PlaceConnectorHolder",
        "Place a typed connector holder at a specified position and orientation on the assembly board.",
        props,
    )


def _route_wire_capability(wire_routing_config) -> model.SubmodelElementCollection:
    props = [
        _cap_prop("MaxPegsPerWire", "32"),
        _cap_prop(
            "InsertionApproachDistanceM",
            str(wire_routing_config.insertion_approach_distance_m)
            if wire_routing_config else "0.08",
        ),
        _cap_prop(
            "PullTestEnabled",
            "true" if (wire_routing_config and wire_routing_config.pull_test_thresholds) else "false",
            condition=SM_IDs.CONDITION_OPTIONAL,
        ),
        _cap_prop("SupportedTerminalTypes", "pin,socket,ring,spade,blade,splice"),
    ]
    return _capability_smc(
        "RouteWire",
        "Retrieve a pre-crimped wire and route it through an ordered sequence of pegs, then insert both ends into the target connector cavities.",
        props,
    )


def _apply_wire_protection_capability() -> model.SubmodelElementCollection:
    props = [
        _cap_prop("SupportedProtectionTypes", "tape,tube,conduit,sleeve,grommet"),
        _cap_prop("PositionResolution", "0.01", condition=SM_IDs.CONDITION_OPTIONAL),
    ]
    return _capability_smc(
        "ApplyWireProtection",
        "Apply a wire protection material (tape, tube, conduit, sleeve, grommet) over a parametric span of a cable segment.",
        props,
    )


def _apply_fixing_capability() -> model.SubmodelElementCollection:
    props = [
        _cap_prop("SupportedFixingTypes", "cable_tie,clip,clamp"),
        _cap_prop("PositionResolution", "0.01", condition=SM_IDs.CONDITION_OPTIONAL),
    ]
    return _capability_smc(
        "ApplyFixing",
        "Apply a cable fixing (tie, clip, clamp) at a specified position on a segment.",
        props,
    )


def _remove_harness_capability() -> model.SubmodelElementCollection:
    props = [
        _cap_prop("RequiresBoardClear", "true"),
    ]
    return _capability_smc(
        "RemoveHarness",
        "Remove the completed wire harness from the assembly board and transfer it downstream.",
        props,
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_capability_description(
    submodel_id: str,
    station_config,
    wire_routing_config=None,
) -> model.Submodel:
    """Build a CapabilityDescription submodel (IDTA 02020-1-0).

    Args:
        submodel_id: The unique AAS submodel ID.
        station_config: StationConfig (board dimensions used for position constraints).
        wire_routing_config: Optional WireRoutingConfig (pull-test thresholds, etc.).

    Returns:
        A Submodel with one CapabilitySet containing all six process capabilities.
    """
    board = station_config.board

    capability_smcs = [
        _place_peg_capability(board),
        _place_connector_holder_capability(board),
        _route_wire_capability(wire_routing_config),
        _apply_wire_protection_capability(),
        _apply_fixing_capability(),
        _remove_harness_capability(),
    ]

    capability_set = model.SubmodelElementCollection(
        "CapabilitySet",
        value=capability_smcs,
        semantic_id=_sem(SM_IDs.CAPABILITY_SET),
    )

    return model.Submodel(
        submodel_id,
        submodel_element=[capability_set],
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
