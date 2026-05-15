"""
Peg placement algorithm.
"""

import math

from ..LayoutModels import (
    BoardConfig,
    LayoutParameters,
    Node,
    PegPlacementReason,
    PegPosition,
    Point2D,
    Segment,
    WireHarness,
)


class PegPlacementEngine:
    """
    Places cable support pegs along segments.

    Placement rules:
    1. Breakout points: Place peg at nodes with degree > 1
    2. Interval placement: Regular spacing along segments
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

        # Build lookup map for node connectivity
        self._node_segments: dict[str, list[str]] = self._build_node_segments_map()
        self._segment_map: dict[str, Segment] = {segment.id: segment for segment in self.harness.segments}
        self._segment_cable_count: dict[str, int] = self._build_segment_cable_count_map()

        self._peg_counter = 0
        self.intersection_offset_applied_count = 0
        self.intersection_offset_fallback_count = 0
        self.intersection_offset_clamped_count = 0

    def _build_node_segments_map(self) -> dict[str, list[str]]:
        """Build a map of node_id -> list of segment IDs connected to that node."""
        node_segments: dict[str, list[str]] = {}

        for segment in self.harness.segments:
            # In new CDM, segments have embedded Node objects
            for node_id in [segment.start_node.id, segment.end_node.id]:
                if node_id not in node_segments:
                    node_segments[node_id] = []
                node_segments[node_id].append(segment.id)

        return node_segments

    def _build_segment_cable_count_map(self) -> dict[str, int]:
        """Build a map of segment_id -> number of cable connections that use it."""
        segment_cable_count = {segment.id: 0 for segment in self.harness.segments}
        for connection in getattr(self.harness, "connections", []) or []:
            for connection_segment in getattr(connection, "segments", []) or []:
                segment_id = getattr(connection_segment, "id", None)
                if segment_id in segment_cable_count:
                    segment_cable_count[segment_id] += 1
        return segment_cable_count

    def _get_node_degree(self, node_id: str) -> int:
        """Get the degree (number of connected segments) of a node."""
        return len(self._node_segments.get(node_id, []))

    def _generate_peg_id(self) -> str:
        """Generate a unique peg ID."""
        self._peg_counter += 1
        return f"peg_{self._peg_counter:04d}"

    def place_pegs(self) -> list[PegPosition]:
        """
        Generate positions for all pegs.

        Returns:
            List of PegPosition objects
        """
        self.intersection_offset_applied_count = 0
        self.intersection_offset_fallback_count = 0
        self.intersection_offset_clamped_count = 0

        all_pegs: list[PegPosition] = []
        processed_breakout_nodes: set[str] = set()

        for segment in self.harness.segments:
            segment_pegs = self._place_pegs_for_segment(
                segment,
                processed_breakout_nodes
            )
            all_pegs.extend(segment_pegs)

        return all_pegs

    def _place_pegs_for_segment(
        self,
        segment: Segment,
        processed_breakout_nodes: set[str],
    ) -> list[PegPosition]:
        """Place pegs for a single segment."""
        pegs: list[PegPosition] = []

        # In new CDM, segments have embedded Node objects
        start_node = segment.start_node
        end_node = segment.end_node

        # Rule 1: Breakout points
        breakout_pegs = self._place_breakout_pegs(
            segment,
            start_node,
            end_node,
            processed_breakout_nodes
        )
        pegs.extend(breakout_pegs)

        # Rule 2: Interval placement
        interval_pegs = self._place_interval_pegs(segment, start_node, end_node)
        pegs.extend(interval_pegs)

        return pegs

    def _place_breakout_pegs(
        self,
        segment: Segment,
        start_node: Node,
        end_node: Node,
        processed_nodes: set[str],
    ) -> list[PegPosition]:
        """Place pegs at breakout points (nodes with degree > 1)."""
        pegs: list[PegPosition] = []

        # Calculate orientation perpendicular to segment
        orientation = self._calculate_perpendicular_orientation(start_node, end_node)

        for node in [start_node, end_node]:
            if node.id in processed_nodes:
                continue

            degree = self._get_node_degree(node.id)
            if degree > 1:
                # This is a breakout point
                position = Point2D(
                    x=node.position.coord_x + self.board_config.offset_x,
                    y=node.position.coord_y + self.board_config.offset_y,
                )
                position = self._apply_intersection_offset(node.id, position)

                pegs.append(PegPosition(
                    id=self._generate_peg_id(),
                    position=position,
                    segment_id=segment.id,
                    reason=PegPlacementReason.BREAKOUT_POINT,
                    orientation_deg=orientation,
                ))

                processed_nodes.add(node.id)

        return pegs

    def _apply_intersection_offset(self, node_id: str, node_position: Point2D) -> Point2D:
        """Offset breakout peg along the selected connected segment."""
        offset_distance_mm = self.parameters.intersection_offset_mm
        if offset_distance_mm <= 0.0:
            return node_position

        offset_selection = self._compute_intersection_offset_direction(node_id)
        if offset_selection is None:
            self.intersection_offset_fallback_count += 1
            return node_position
        offset_direction, preferred_segment_id = offset_selection

        shifted_position = Point2D(
            x=node_position.x + offset_direction.x * offset_distance_mm,
            y=node_position.y + offset_direction.y * offset_distance_mm,
        )
        validated_position = shifted_position
        if not self._is_point_on_segment_id(preferred_segment_id, validated_position):
            projected_position = self._project_point_to_segment_id(preferred_segment_id, validated_position)
            if projected_position is None:
                self.intersection_offset_fallback_count += 1
                return node_position
            validated_position = projected_position

        self.intersection_offset_applied_count += 1
        clamped_position, was_clamped = self._keep_point_inside_board(validated_position)
        if was_clamped:
            self.intersection_offset_clamped_count += 1
            if not self._is_point_on_segment_id(preferred_segment_id, clamped_position):
                projected_position = self._project_point_to_segment_id(preferred_segment_id, clamped_position)
                if projected_position is not None:
                    clamped_position = projected_position
                else:
                    self.intersection_offset_fallback_count += 1
                    return node_position

        return clamped_position

    def _compute_intersection_offset_direction(self, node_id: str) -> tuple[Point2D, str] | None:
        """
        Compute offset direction aligned with selected connected segment.

        Priority: segment with highest cable count. Tie-breakers: longer segment,
        then lexicographically smaller segment id for deterministic behavior.
        If no cable counts are available, fallback to weighted-geometry selection.
        """
        epsilon_value = 1e-6
        node_direction_vectors: list[tuple[float, float, float, str, int]] = []

        for segment in self.harness.segments:
            if segment.start_node.id == node_id:
                other_node = segment.end_node
                node_x_value = segment.start_node.position.coord_x
                node_y_value = segment.start_node.position.coord_y
            elif segment.end_node.id == node_id:
                other_node = segment.start_node
                node_x_value = segment.end_node.position.coord_x
                node_y_value = segment.end_node.position.coord_y
            else:
                continue

            delta_x = other_node.position.coord_x - node_x_value
            delta_y = other_node.position.coord_y - node_y_value
            magnitude_value = math.sqrt(delta_x ** 2 + delta_y ** 2)
            if magnitude_value <= epsilon_value:
                continue

            node_direction_vectors.append(
                (
                    delta_x / magnitude_value,
                    delta_y / magnitude_value,
                    magnitude_value,
                    segment.id,
                    self._segment_cable_count.get(segment.id, 0),
                )
            )

        if not node_direction_vectors:
            return None

        best_by_cable = sorted(
            node_direction_vectors,
            key=lambda item: (-item[4], -item[2], item[3]),
        )[0]
        if best_by_cable[4] > 0:
            return Point2D(x=best_by_cable[0], y=best_by_cable[1]), best_by_cable[3]

        weighted_x = sum(unit_x * segment_length for unit_x, _, segment_length, _, _ in node_direction_vectors)
        weighted_y = sum(unit_y * segment_length for _, unit_y, segment_length, _, _ in node_direction_vectors)
        weighted_magnitude = math.sqrt(weighted_x ** 2 + weighted_y ** 2)
        if weighted_magnitude <= epsilon_value:
            return None

        preferred_x = weighted_x / weighted_magnitude
        preferred_y = weighted_y / weighted_magnitude
        selected_direction: tuple[float, float] | None = None
        selected_dot_product = -float("inf")
        selected_segment_id = ""

        for unit_x, unit_y, _, segment_id, _ in node_direction_vectors:
            dot_product = unit_x * preferred_x + unit_y * preferred_y
            if dot_product > selected_dot_product + epsilon_value:
                selected_dot_product = dot_product
                selected_direction = (unit_x, unit_y)
                selected_segment_id = segment_id
            elif abs(dot_product - selected_dot_product) <= epsilon_value and segment_id < selected_segment_id:
                selected_direction = (unit_x, unit_y)
                selected_segment_id = segment_id

        if selected_direction is None:
            return None

        return Point2D(x=selected_direction[0], y=selected_direction[1]), selected_segment_id

    def _keep_point_inside_board(self, point: Point2D) -> tuple[Point2D, bool]:
        """Clamp point to board bounds and report if clamped."""
        min_x = 0.0
        min_y = 0.0
        max_x = self.board_config.width_mm
        max_y = self.board_config.height_mm

        clamped_x = min(max(point.x, min_x), max_x)
        clamped_y = min(max(point.y, min_y), max_y)
        was_clamped = (clamped_x != point.x) or (clamped_y != point.y)
        return Point2D(x=clamped_x, y=clamped_y), was_clamped

    def _is_point_on_segment_id(self, segment_id: str, point: Point2D) -> bool:
        """Check whether point lies on specific segment."""
        segment = self._segment_map.get(segment_id)
        if segment is None:
            return False
        start_x = segment.start_node.position.coord_x + self.board_config.offset_x
        start_y = segment.start_node.position.coord_y + self.board_config.offset_y
        end_x = segment.end_node.position.coord_x + self.board_config.offset_x
        end_y = segment.end_node.position.coord_y + self.board_config.offset_y
        return self._distance_point_to_segment(point.x, point.y, start_x, start_y, end_x, end_y) <= 1e-3

    def _project_point_to_segment_id(self, segment_id: str, point: Point2D) -> Point2D | None:
        """Project point to specific segment."""
        segment = self._segment_map.get(segment_id)
        if segment is None:
            return None
        start_x = segment.start_node.position.coord_x + self.board_config.offset_x
        start_y = segment.start_node.position.coord_y + self.board_config.offset_y
        end_x = segment.end_node.position.coord_x + self.board_config.offset_x
        end_y = segment.end_node.position.coord_y + self.board_config.offset_y
        projection_x, projection_y = self._project_point_to_segment(
            point.x, point.y, start_x, start_y, end_x, end_y
        )
        return Point2D(x=projection_x, y=projection_y)

    def _project_point_to_segment(
        self,
        point_x: float,
        point_y: float,
        segment_start_x: float,
        segment_start_y: float,
        segment_end_x: float,
        segment_end_y: float,
    ) -> tuple[float, float]:
        """Project point to segment and return closest segment point."""
        segment_delta_x = segment_end_x - segment_start_x
        segment_delta_y = segment_end_y - segment_start_y
        segment_length_sq = segment_delta_x ** 2 + segment_delta_y ** 2
        if segment_length_sq <= 1e-9:
            return segment_start_x, segment_start_y

        projection_factor = (
            (point_x - segment_start_x) * segment_delta_x
            + (point_y - segment_start_y) * segment_delta_y
        ) / segment_length_sq
        projection_factor = min(max(projection_factor, 0.0), 1.0)
        return (
            segment_start_x + projection_factor * segment_delta_x,
            segment_start_y + projection_factor * segment_delta_y,
        )

    def _distance_point_to_segment(
        self,
        point_x: float,
        point_y: float,
        segment_start_x: float,
        segment_start_y: float,
        segment_end_x: float,
        segment_end_y: float,
    ) -> float:
        """Compute Euclidean distance between point and finite segment."""
        nearest_x, nearest_y = self._project_point_to_segment(
            point_x,
            point_y,
            segment_start_x,
            segment_start_y,
            segment_end_x,
            segment_end_y,
        )
        return math.sqrt((point_x - nearest_x) ** 2 + (point_y - nearest_y) ** 2)

    def _place_interval_pegs(
        self,
        segment: Segment,
        start_node: Node,
        end_node: Node,
    ) -> list[PegPosition]:
        """Place pegs at regular intervals along the segment."""
        pegs: list[PegPosition] = []

        interval = self.parameters.default_peg_interval_mm

        # Calculate segment length (use stored length or compute from nodes)
        segment_length = segment.length if segment.length else 0.0
        if segment_length <= 0:
            # Fallback: compute from node positions
            start_x = start_node.position.coord_x
            start_y = start_node.position.coord_y
            end_x = end_node.position.coord_x
            end_y = end_node.position.coord_y
            segment_length = math.sqrt(
                (end_x - start_x) ** 2 +
                (end_y - start_y) ** 2
            )

        # Skip if segment is shorter than interval
        if segment_length < interval:
            return pegs

        # Calculate number of pegs
        num_pegs = int(segment_length / interval)

        # Calculate orientation perpendicular to segment
        orientation = self._calculate_perpendicular_orientation(start_node, end_node)

        # Place pegs evenly distributed
        for index in range(1, num_pegs + 1):
            interpolation_factor = index / (num_pegs + 1)
            position = self._interpolate_position(
                start_node,
                end_node,
                interpolation_factor
            )

            pegs.append(PegPosition(
                id=self._generate_peg_id(),
                position=position,
                segment_id=segment.id,
                reason=PegPlacementReason.INTERVAL,
                orientation_deg=orientation,
            ))

        return pegs

    def _interpolate_position(
        self,
        start_node: Node,
        end_node: Node,
        interpolation_factor: float
    ) -> Point2D:
        """
        Interpolate a position between two nodes.

        Args:
            start_node: Starting node
            end_node: Ending node
            interpolation_factor: Value between 0 and 1 (0 = start, 1 = end)

        Returns:
            Interpolated Point2D in board coordinates
        """
        start_x = start_node.position.coord_x
        start_y = start_node.position.coord_y
        end_x = end_node.position.coord_x
        end_y = end_node.position.coord_y

        interpolated_x = start_x + interpolation_factor * (end_x - start_x)
        interpolated_y = start_y + interpolation_factor * (end_y - start_y)

        return Point2D(
            x=interpolated_x + self.board_config.offset_x,
            y=interpolated_y + self.board_config.offset_y,
        )

    def _calculate_perpendicular_orientation(
        self,
        start_node: Node,
        end_node: Node,
    ) -> float:
        """
        Calculate peg orientation perpendicular to segment direction.

        Args:
            start_node: Starting node of the segment
            end_node: Ending node of the segment

        Returns:
            Orientation angle in degrees (perpendicular to segment)
        """
        delta_x = end_node.position.coord_x - start_node.position.coord_x
        delta_y = end_node.position.coord_y - start_node.position.coord_y

        # Calculate segment direction angle
        segment_angle_rad = math.atan2(delta_y, delta_x)

        # Add 90 degrees to get perpendicular orientation
        perpendicular_angle_rad = segment_angle_rad + math.pi / 2

        # Convert to degrees
        return math.degrees(perpendicular_angle_rad)
