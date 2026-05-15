"""
Connector holder placement algorithm.
"""

import math

from ..LayoutConfig import DEFAULT_PARAMETERS
from ..LayoutModels import (
    BoardConfig,
    ConnectorHolderPosition,
    ConnectorOccurrence,
    HolderType,
    LayoutParameters,
    Node,
    Point2D,
    Segment,
    Vector2D,
    WireHarness,
)


class ConnectorPlacementEngine:
    """
    Places connector holders on the assembly board.

    Responsibilities:
    - Transform connector positions from CDM to board coordinates
    - Compute mating direction vectors
    - Determine holder types based on connector dimensions
    - Apply buffer zones
    """

    def __init__(
        self,
        harness: WireHarness,
        board_config: BoardConfig,
        parameters: LayoutParameters,
    ):
        self.harness = harness
        self.board_config = board_config
        self.parameters = parameters

        # Build lookup maps
        self._node_map: dict[str, Node] = {node.id: node for node in harness.nodes}
        self._node_segments: dict[str, list[Segment]] = self._build_node_segments_map()

    def _build_node_segments_map(self) -> dict[str, list[Segment]]:
        """Build a map of node_id -> list of segments connected to that node."""
        node_segments: dict[str, list[Segment]] = {}

        for segment in self.harness.segments:
            # In new CDM, segments have embedded Node objects
            for node_id in [segment.start_node.id, segment.end_node.id]:
                if node_id not in node_segments:
                    node_segments[node_id] = []
                node_segments[node_id].append(segment)

        return node_segments

    def place_connectors(self) -> list[ConnectorHolderPosition]:
        """
        Generate positions for all connector holders.

        Returns:
            List of ConnectorHolderPosition objects
        """
        holder_positions: list[ConnectorHolderPosition] = []

        for connector_occ in self.harness.connector_occurrences:
            position = self._place_single_connector(connector_occ)
            if position:
                holder_positions.append(position)

        return holder_positions

    def _place_single_connector(
        self,
        connector_occ: ConnectorOccurrence
    ) -> ConnectorHolderPosition | None:
        """
        Place a single connector holder.

        The connector is offset inward along the cable direction to allow
        cable slack/hanging between the connector and the harness.
        """
        # Get the node position - either from node_id reference or connector position
        node = None
        node_x = 0.0
        node_y = 0.0

        if connector_occ.node_id:
            node = self._node_map.get(connector_occ.node_id)
            if node is None:
                return None  # Skip connector with missing node reference
            node_x = node.position.coord_x
            node_y = node.position.coord_y
        elif connector_occ.position:
            # Use the connector's own position
            node_x = connector_occ.position.coord_x
            node_y = connector_occ.position.coord_y
        else:
            return None  # Skip connector with no position

        # Compute mating direction (points toward cable exit / interior)
        mating_direction = self._compute_mating_direction(connector_occ, node)
        orientation_deg = mating_direction.to_angle_deg() if mating_direction else 0.0

        # Calculate inward offset along cable direction
        # The connector is placed offset from the node toward the interior
        # to allow cable slack/hanging
        inward_offset = DEFAULT_PARAMETERS.connector_inward_offset_mm

        if mating_direction:
            # Offset position along the mating direction (toward interior)
            offset_x = mating_direction.x * inward_offset
            offset_y = mating_direction.y * inward_offset
        else:
            offset_x = 0.0
            offset_y = 0.0

        # Transform to board coordinates with inward offset
        board_position = Point2D(
            x=node_x + self.board_config.offset_x + offset_x,
            y=node_y + self.board_config.offset_y + offset_y,
        )

        # Determine holder type
        holder_type = self._determine_holder_type(connector_occ)

        return ConnectorHolderPosition(
            connector_id=connector_occ.id,
            position=board_position,
            orientation_deg=orientation_deg,
            holder_type=holder_type,
            buffer_radius_mm=self.parameters.connector_buffer_zone_mm,
            width_mm=connector_occ.physical_width,
            height_mm=connector_occ.physical_height,
        )

    def _compute_mating_direction(
        self,
        connector_occ: ConnectorOccurrence,
        node: Node | None,
    ) -> Vector2D | None:
        """
        Compute the mating direction for a connector.

        The mating direction points from the connector toward the cable exit,
        i.e., toward the first branch/segment node.
        """
        # If mating direction is already specified, use it
        if connector_occ.mating_direction:
            return connector_occ.mating_direction.normalize()

        # Need a node to compute direction from segments
        if node is None:
            return Vector2D(x=1.0, y=0.0)

        # Find segments connected to this node
        connected_segments = self._node_segments.get(node.id, [])

        if not connected_segments:
            # No segments, default to pointing right
            return Vector2D(x=1.0, y=0.0)

        # Compute average direction toward connected nodes
        direction_sum_x = 0.0
        direction_sum_y = 0.0
        valid_directions = 0

        node_x = node.position.coord_x
        node_y = node.position.coord_y

        for segment in connected_segments:
            # Find the other node (segments have embedded Node objects)
            other_node = (
                segment.end_node
                if segment.start_node.id == node.id
                else segment.start_node
            )

            # Direction from this node to other node
            direction_x = other_node.position.coord_x - node_x
            direction_y = other_node.position.coord_y - node_y

            # Normalize
            magnitude = math.sqrt(direction_x ** 2 + direction_y ** 2)
            if magnitude > 0:
                direction_sum_x += direction_x / magnitude
                direction_sum_y += direction_y / magnitude
                valid_directions += 1

        if valid_directions == 0:
            return Vector2D(x=1.0, y=0.0)

        # Average direction
        avg_direction = Vector2D(
            x=direction_sum_x / valid_directions,
            y=direction_sum_y / valid_directions,
        )

        return avg_direction.normalize()

    def _determine_holder_type(self, connector_occ: ConnectorOccurrence) -> HolderType:
        """
        Determine the holder type based on connector dimensions.

        Categories:
        - SMALL: max dimension < 30mm
        - MEDIUM: max dimension 30-60mm
        - LARGE: max dimension > 60mm
        """
        max_dimension = max(connector_occ.physical_width, connector_occ.physical_height)

        if max_dimension < DEFAULT_PARAMETERS.holder_small_threshold_mm:
            return HolderType.SMALL
        elif max_dimension <= DEFAULT_PARAMETERS.holder_medium_threshold_mm:
            return HolderType.MEDIUM
        else:
            return HolderType.LARGE
