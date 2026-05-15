"""
Layout optimization: merging nearby positions and forbidden zone handling.
"""

import math

from ..LayoutModels import (
    BoardConfig,
    ConnectorHolderPosition,
    LayoutParameters,
    PegPlacementReason,
    PegPosition,
    Point2D,
)


class LayoutOptimizer:
    """
    Optimizes the layout by:
    1. Merging nearby pegs (within merge_distance_mm)
    2. Avoiding forbidden zones
    3. Keeping pegs away from connector holder buffer zones
    """

    def __init__(
        self,
        board_config: BoardConfig,
        parameters: LayoutParameters,
    ):
        self.board_config = board_config
        self.parameters = parameters
        self.forbidden_zones = list(board_config.forbidden_zones)
        self.merged_count = 0
        self.shifted_count = 0

    def optimize(
        self,
        connector_holders: list[ConnectorHolderPosition],
        pegs: list[PegPosition],
    ) -> tuple[list[ConnectorHolderPosition], list[PegPosition]]:
        """
        Optimize the layout.

        Args:
            connector_holders: List of connector holder positions
            pegs: List of peg positions

        Returns:
            Tuple of (optimized_holders, optimized_pegs)
        """
        self.merged_count = 0
        self.shifted_count = 0

        # Step 1: Merge nearby pegs
        merged_pegs = self._merge_nearby_pegs(pegs)

        # Step 2: Remove pegs too close to connector holders
        filtered_pegs = self._filter_pegs_near_connectors(merged_pegs, connector_holders)

        # Step 3: Shift pegs out of forbidden zones
        shifted_pegs = self._shift_from_forbidden_zones(filtered_pegs)

        # Connector holders are not moved (they are fixed anchors)
        return connector_holders, shifted_pegs

    def _merge_nearby_pegs(self, pegs: list[PegPosition]) -> list[PegPosition]:
        """Merge pegs that are within merge_distance_mm of each other."""
        if not pegs:
            return pegs

        merged: list[PegPosition] = []
        used_indices: set[int] = set()

        for index, peg in enumerate(pegs):
            if index in used_indices:
                continue

            # Find all pegs within merge distance
            cluster_indices = [index]
            cluster_positions = [peg]

            for other_index, other_peg in enumerate(pegs[index + 1:], start=index + 1):
                if other_index in used_indices:
                    continue

                distance = self._distance(peg.position, other_peg.position)
                if distance < self.parameters.merge_distance_mm:
                    cluster_indices.append(other_index)
                    cluster_positions.append(other_peg)

            # Mark all as used
            used_indices.update(cluster_indices)

            if len(cluster_positions) == 1:
                # No merge needed
                merged.append(peg)
            else:
                # Merge into single peg at centroid
                merged_peg = self._merge_peg_cluster(cluster_positions)
                merged.append(merged_peg)
                self.merged_count += len(cluster_positions) - 1

        return merged

    def _merge_peg_cluster(self, cluster: list[PegPosition]) -> PegPosition:
        """Merge a cluster of pegs into a single peg at the centroid."""
        # Calculate centroid
        centroid_x = sum(p.position.x for p in cluster) / len(cluster)
        centroid_y = sum(p.position.y for p in cluster) / len(cluster)

        # Prefer BREAKOUT_POINT over INTERVAL
        best_peg = next(
            (p for p in cluster if p.reason == PegPlacementReason.BREAKOUT_POINT),
            cluster[0]
        )
        best_reason = best_peg.reason

        # Track merged IDs
        merged_ids = ",".join(p.id for p in cluster)

        return PegPosition(
            id=cluster[0].id,  # Keep first ID
            position=Point2D(x=centroid_x, y=centroid_y),
            segment_id=cluster[0].segment_id,
            reason=best_reason,
            orientation_deg=best_peg.orientation_deg,  # Use orientation from highest-priority peg
            merged_from=merged_ids,
        )

    def _filter_pegs_near_connectors(
        self,
        pegs: list[PegPosition],
        connectors: list[ConnectorHolderPosition],
    ) -> list[PegPosition]:
        """Remove pegs that are within connector buffer zones."""
        if not connectors:
            return pegs

        filtered: list[PegPosition] = []

        for peg in pegs:
            is_in_buffer = False

            for connector in connectors:
                distance = self._distance(peg.position, connector.position)
                if distance < connector.buffer_radius_mm:
                    is_in_buffer = True
                    break

            if not is_in_buffer:
                filtered.append(peg)

        return filtered

    def _shift_from_forbidden_zones(
        self,
        pegs: list[PegPosition]
    ) -> list[PegPosition]:
        """Shift pegs that are in forbidden zones to nearest valid position."""
        shifted: list[PegPosition] = []

        for peg in pegs:
            if self._is_in_forbidden_zone(peg.position):
                new_position = self._find_nearest_valid_position(peg.position)
                if new_position:
                    shifted_peg = PegPosition(
                        id=peg.id,
                        position=new_position,
                        segment_id=peg.segment_id,
                        reason=peg.reason,
                        orientation_deg=peg.orientation_deg,
                        merged_from=peg.merged_from,
                    )
                    shifted.append(shifted_peg)
                    self.shifted_count += 1
                else:
                    # Could not find valid position, keep original
                    shifted.append(peg)
            else:
                shifted.append(peg)

        return shifted

    def _is_in_forbidden_zone(self, point: Point2D) -> bool:
        """Check if a point is inside any forbidden zone."""
        for zone in self.forbidden_zones:
            if self._point_in_polygon(point, zone.vertices):
                return True
        return False

    def _point_in_polygon(self, point: Point2D, vertices: list[Point2D]) -> bool:
        """
        Check if a point is inside a polygon using ray casting algorithm.
        """
        if len(vertices) < 3:
            return False

        num_vertices = len(vertices)
        inside = False

        point_x, point_y = point.x, point.y
        vertex_j = num_vertices - 1

        for vertex_i in range(num_vertices):
            vertex_i_x, vertex_i_y = vertices[vertex_i].x, vertices[vertex_i].y
            vertex_j_x, vertex_j_y = vertices[vertex_j].x, vertices[vertex_j].y

            if ((vertex_i_y > point_y) != (vertex_j_y > point_y)) and \
               (point_x < (vertex_j_x - vertex_i_x) * (point_y - vertex_i_y) / (vertex_j_y - vertex_i_y) + vertex_i_x):
                inside = not inside

            vertex_j = vertex_i

        return inside

    def _find_nearest_valid_position(self, point: Point2D) -> Point2D | None:
        """
        Find the nearest position outside all forbidden zones.

        Uses a simple search in cardinal directions.
        """
        step_size = 10.0  # mm
        max_search_distance = 300.0  # mm

        # Search in 8 directions
        directions = [
            (1, 0), (-1, 0), (0, 1), (0, -1),
            (1, 1), (1, -1), (-1, 1), (-1, -1),
        ]

        for distance in range(int(step_size), int(max_search_distance), int(step_size)):
            for direction_x, direction_y in directions:
                # Normalize diagonal directions
                magnitude = math.sqrt(direction_x ** 2 + direction_y ** 2)
                normalized_x = direction_x / magnitude
                normalized_y = direction_y / magnitude

                candidate = Point2D(
                    x=point.x + normalized_x * distance,
                    y=point.y + normalized_y * distance,
                )

                # Check if within board bounds
                if not self._is_within_board(candidate):
                    continue

                # Check if outside all forbidden zones
                if not self._is_in_forbidden_zone(candidate):
                    return candidate

        return None

    def _is_within_board(self, point: Point2D) -> bool:
        """Check if a point is within board boundaries."""
        return (
            0 <= point.x <= self.board_config.width_mm and
            0 <= point.y <= self.board_config.height_mm
        )

    def _distance(self, point_a: Point2D, point_b: Point2D) -> float:
        """Calculate Euclidean distance between two points."""
        return math.sqrt(
            (point_a.x - point_b.x) ** 2 +
            (point_a.y - point_b.y) ** 2
        )
