"""
Builder: SimConfig objects → MaterialDeliveryAAS.
"""

from ..shells.material_delivery_aas import (
    MaterialDeliveryAASBundle,
    build_material_delivery_aas,
)


def build_aas_from_delivery_config(
    station_id: str,
    board_setup_config=None,
    wire_routing_config=None,
    manufacturer_name: str = "NEXUS",
) -> MaterialDeliveryAASBundle:
    """Build a MaterialDeliveryAAS from simulation config objects.

    Args:
        station_id: Station identifier.
        board_setup_config: Optional BoardSetupConfig (peg/holder pickup positions).
        wire_routing_config: Optional WireRoutingConfig (wire-end pickup positions).
        manufacturer_name: Organisation operating the station.

    Returns:
        MaterialDeliveryAASBundle (shell + 2 submodels).
    """
    return build_material_delivery_aas(
        station_id,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
        manufacturer_name=manufacturer_name,
    )
