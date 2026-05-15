"""
Wire Routing Order Engine.

Computes the optimal sequence for routing wires during harness assembly,
based on a 5-tier priority system:

    Priority 1 -- Inner cavity first (CRITICAL):
        Wires targeting inner cavity positions are routed before outer ones,
        ensuring maximum mechanical accessibility during insertion.

    Priority 2 -- Trunk-first layering:
        Wires traversing high-traffic trunk segments are routed first,
        building bundles from the inside out.

    Priority 3 -- Shared-path grouping:
        Wires sharing the same segment set are grouped consecutively,
        minimizing robot context switching.

    Priority 4 -- Longer wires first:
        Longer wires are routed while the board is less crowded.

    Priority 5 -- Connector-pair grouping:
        Wires connecting the same connector pair are grouped together,
        reducing approach direction changes.
"""

import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add parent directory to path for CDM imports
_parent_dir = Path(__file__).resolve().parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

from public.cdm.definitions.cdm_schema import (
    Connection,
    ConnectorOccurrence,
    WireOccurrence,
)

UNKNOWN_CAVITY_PRIORITY = 1_000_000


class WireRoutingOrderEngine:
    """Computes optimal wire routing sequence based on 5-tier priority criteria."""

    def compute_routing_order(
        self,
        connections: List[Connection],
        connector_occurrences: List[ConnectorOccurrence],
    ) -> List[Connection]:
        """Return connections sorted by the 5-tier routing priority.

        Args:
            connections: All connections in the harness.
            connector_occurrences: All connector occurrences (needed to map
                contact points to connectors and cavity numbers).

        Returns:
            The same connections list, sorted by routing priority (first element
            should be routed first).
        """
        if not connections:
            return []

        contact_point_lookup = self._build_contact_point_lookup(connector_occurrences)
        segment_wire_count = self._count_wires_per_segment(connections)

        def sort_key(connection: Connection) -> Tuple:
            return (
                self._priority_inner_cavity(connection, contact_point_lookup),
                self._priority_trunk_first(connection, segment_wire_count),
                self._priority_shared_path(connection),
                self._priority_longer_first(connection),
                self._priority_connector_pair(connection, contact_point_lookup),
            )

        return sorted(connections, key=sort_key)

    # ------------------------------------------------------------------
    # Priority 1: Inner cavity first (ascending by min cavity number)
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_inner_cavity(
        connection: Connection,
        contact_point_lookup: Dict[str, Dict],
    ) -> int:
        """Lower cavity number = higher priority (routes first).

        Uses the minimum cavity number across all extremities so that wires
        targeting the most-inner cavity are routed earliest.
        """
        cavity_numbers: List[int] = []
        for extremity in connection.extremities:
            info = contact_point_lookup.get(extremity.contact_point.id)
            if info is not None:
                cavity_numbers.append(info["cavity_number"])

        return min(cavity_numbers) if cavity_numbers else UNKNOWN_CAVITY_PRIORITY

    # ------------------------------------------------------------------
    # Priority 2: Trunk-first layering (descending by traffic, negated)
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_trunk_first(
        connection: Connection,
        segment_wire_count: Dict[str, int],
    ) -> int:
        """Higher segment traffic = higher priority (routes first).

        The trunk score is the sum of wire counts on the connection's segments.
        Negated so that ascending sort gives trunk-heavy wires first.
        """
        trunk_score = sum(
            segment_wire_count.get(segment.id, 0)
            for segment in connection.segments
        )
        return -trunk_score

    # ------------------------------------------------------------------
    # Priority 3: Shared-path grouping (group by segment ID tuple)
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_shared_path(connection: Connection) -> Tuple[str, ...]:
        """Wires sharing the same segment set are grouped together."""
        return tuple(sorted(segment.id for segment in connection.segments))

    # ------------------------------------------------------------------
    # Priority 4: Longer wires first (descending by length, negated)
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_longer_first(connection: Connection) -> float:
        """Longer wires route first (less crowded board).

        Negated so ascending sort gives longer wires first.
        """
        wire_occurrence = connection.wire_occurrence

        # WireOccurrence has length_dmu; SpecialWireOccurrence has length.length_mm
        if isinstance(wire_occurrence, WireOccurrence) and wire_occurrence.length_dmu is not None:
            wire_length = wire_occurrence.length_dmu
        elif hasattr(wire_occurrence, "length") and wire_occurrence.length is not None:
            wire_length = wire_occurrence.length.length_mm
        else:
            # Fallback: sum of segment lengths
            wire_length = sum(
                segment.length or 0.0 for segment in connection.segments
            )

        return -wire_length

    # ------------------------------------------------------------------
    # Priority 5: Connector-pair grouping
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_connector_pair(
        connection: Connection,
        contact_point_lookup: Dict[str, Dict],
    ) -> Tuple[str, ...]:
        """Wires connecting the same pair of connectors are grouped."""
        connector_ids: Set[str] = set()
        for extremity in connection.extremities:
            info = contact_point_lookup.get(extremity.contact_point.id)
            if info is not None:
                connector_ids.add(info["connector_occurrence_id"])

        return tuple(sorted(connector_ids))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_contact_point_lookup(
        connector_occurrences: List[ConnectorOccurrence],
    ) -> Dict[str, Dict]:
        """Build a lookup from contact_point.id to connector/cavity info.

        Returns:
            Dict mapping contact_point_id -> {
                "connector_occurrence_id": str,
                "cavity_number": int,
            }
        """
        lookup: Dict[str, Dict] = {}
        for connector_occurrence in connector_occurrences:
            for contact_point in connector_occurrence.contact_points:
                cavity_number_str = contact_point.cavity.cavity_number
                try:
                    cavity_number = int(cavity_number_str)
                except (ValueError, TypeError):
                    cavity_number = UNKNOWN_CAVITY_PRIORITY

                lookup[contact_point.id] = {
                    "connector_occurrence_id": connector_occurrence.id,
                    "cavity_number": cavity_number,
                }
        return lookup

    @staticmethod
    def _count_wires_per_segment(
        connections: List[Connection],
    ) -> Dict[str, int]:
        """Count how many connections traverse each segment.

        Segments with more connections are trunk/high-traffic segments.
        """
        segment_wire_count: Dict[str, int] = {}
        for connection in connections:
            for segment in connection.segments:
                segment_wire_count[segment.id] = (
                    segment_wire_count.get(segment.id, 0) + 1
                )
        return segment_wire_count
