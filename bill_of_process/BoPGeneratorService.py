"""
BoP Generator Service -- main orchestration logic.

Derives a ProductionBillOfProcess from one or more (WireHarness + LayoutResponse)
inputs combined with station configuration.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory to path for CDM / layout imports
_parent_dir = Path(__file__).resolve().parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

from layout_generator.LayoutModels import LayoutResponse, PegPosition
from public.cdm.definitions.cdm_schema import ConnectorOccurrence, Segment

from .BoPConfig import BoPGeneratorConfig, HarnessInput
from .BoPModels import (
    ApplyFixingParameters,
    ApplyWireProtectionParameters,
    AssemblyPhase,
    HarnessReference,
    PhaseType,
    PlaceConnectorHolderParameters,
    PlacePegParameters,
    ProcessStep,
    ProcessType,
    ProductionBillOfProcess,
    RemoveHarnessParameters,
    RouteWireExtremity,
    RouteWireParameters,
)
from .WireRoutingOrderEngine import WireRoutingOrderEngine


class BoPGeneratorService:
    """Generates a ProductionBillOfProcess from CDM + Layout + Config.

    Pipeline per harness:
        Phase 1 -- Board Setup: PLACE_PEG, PLACE_CONNECTOR_HOLDER
        Phase 2 -- Wire Routing: ROUTE_WIRE (ordered by WireRoutingOrderEngine)
        Phase 3 -- Protection & Fixing: APPLY_WIRE_PROTECTION, APPLY_FIXING
        Phase 4 -- Connector Assembly: (placeholder, no steps in v1)
        Phase 5 -- Finalization: REMOVE_HARNESS
    """

    def __init__(self) -> None:
        self._routing_order_engine = WireRoutingOrderEngine()
        self._sequence_counter = 0

    def generate(self, config: BoPGeneratorConfig) -> ProductionBillOfProcess:
        """Generate a complete BoP from the configuration.

        Args:
            config: Contains production_id, harness inputs, and station info.

        Returns:
            A fully populated ProductionBillOfProcess.
        """
        self._sequence_counter = 0

        harness_refs: List[HarnessReference] = []
        all_board_setup_steps: List[ProcessStep] = []
        all_wire_routing_steps: List[ProcessStep] = []
        all_protection_steps: List[ProcessStep] = []
        all_finalization_steps: List[ProcessStep] = []

        for harness_input in config.harness_inputs:
            harness_refs.append(
                HarnessReference(
                    harness_id=harness_input.harness.id,
                    harness_part_number=harness_input.harness.part_number,
                    station_id=harness_input.station_id,
                    cdm_source=harness_input.cdm_source,
                    layout_source=harness_input.layout_source,
                )
            )

            # Phase 1: Board Setup
            board_setup_steps = self._generate_board_setup(harness_input)
            all_board_setup_steps.extend(board_setup_steps)

            # Phase 2: Wire Routing
            wire_routing_steps = self._generate_wire_routing(harness_input)
            all_wire_routing_steps.extend(wire_routing_steps)

            # Phase 3: Protection & Fixing
            protection_steps = self._generate_protection_and_fixing(harness_input)
            all_protection_steps.extend(protection_steps)

            # Phase 4: Connector Assembly -- placeholder, no steps in v1

            # Phase 5: Finalization
            finalization_steps = self._generate_finalization(harness_input)
            all_finalization_steps.extend(finalization_steps)

        phases = self._assemble_phases(
            all_board_setup_steps,
            all_wire_routing_steps,
            all_protection_steps,
            all_finalization_steps,
        )

        return ProductionBillOfProcess(
            production_id=config.production_id,
            created_at=datetime.now(timezone.utc),
            harness_refs=harness_refs,
            phases=phases,
        )

    # ======================================================================
    # Phase generators
    # ======================================================================

    def _generate_board_setup(
        self, harness_input: HarnessInput
    ) -> List[ProcessStep]:
        """Generate PLACE_PEG and PLACE_CONNECTOR_HOLDER steps."""
        steps: List[ProcessStep] = []
        harness_id = harness_input.harness.id
        station_id = harness_input.station_id
        layout = harness_input.layout_response

        # PLACE_PEG steps
        for peg in layout.pegs:
            steps.append(
                ProcessStep(
                    step_id=self._next_step_id(harness_id, "place_peg"),
                    sequence_number=self._next_sequence(),
                    process_type=ProcessType.PLACE_PEG,
                    harness_id=harness_id,
                    station_id=station_id,
                    description=f"Place peg {peg.id} on segment {peg.segment_id}",
                    parameters=PlacePegParameters(
                        peg_id=peg.id,
                        position_x_mm=peg.position.x,
                        position_y_mm=peg.position.y,
                        orientation_deg=peg.orientation_deg,
                        segment_id=peg.segment_id,
                        placement_reason=str(peg.reason),
                    ),
                )
            )

        # PLACE_CONNECTOR_HOLDER steps
        for holder in layout.connector_holders:
            steps.append(
                ProcessStep(
                    step_id=self._next_step_id(harness_id, "place_holder"),
                    sequence_number=self._next_sequence(),
                    process_type=ProcessType.PLACE_CONNECTOR_HOLDER,
                    harness_id=harness_id,
                    station_id=station_id,
                    description=(
                        f"Place connector holder for {holder.connector_id}"
                    ),
                    parameters=PlaceConnectorHolderParameters(
                        connector_occurrence_id=holder.connector_id,
                        position_x_mm=holder.position.x,
                        position_y_mm=holder.position.y,
                        orientation_deg=holder.orientation_deg,
                        holder_type=str(holder.holder_type),
                        width_mm=holder.width_mm,
                        height_mm=holder.height_mm,
                        buffer_radius_mm=holder.buffer_radius_mm,
                    ),
                )
            )

        return steps

    def _generate_wire_routing(
        self, harness_input: HarnessInput
    ) -> List[ProcessStep]:
        """Generate ROUTE_WIRE steps in priority order."""
        steps: List[ProcessStep] = []
        harness = harness_input.harness
        layout = harness_input.layout_response
        station_id = harness_input.station_id
        harness_id = harness.id

        if not harness.connections:
            return steps

        # Build lookup: contact_point_id -> connector occurrence info
        contact_point_lookup = self._build_contact_point_lookup(
            harness.connector_occurrences
        )

        # Build lookup: segment_id -> list of pegs (from layout)
        segment_pegs_map = self._build_segment_pegs_map(layout.pegs)

        # Compute routing order
        ordered_connections = self._routing_order_engine.compute_routing_order(
            harness.connections,
            harness.connector_occurrences,
        )

        for connection in ordered_connections:
            wire_occurrence = connection.wire_occurrence

            # Determine ordered peg IDs along the wire's route
            ordered_peg_ids = self._compute_ordered_peg_ids(
                connection.segments, segment_pegs_map
            )

            # Build extremity info
            extremities: List[RouteWireExtremity] = []
            for extremity in connection.extremities:
                contact_point = extremity.contact_point
                connector_info = contact_point_lookup.get(contact_point.id)
                if connector_info is None:
                    raise ValueError(
                        "Contact point is not mapped to a connector occurrence: "
                        f"connection_id={connection.id}, "
                        f"contact_point_id={contact_point.id}"
                    )

                extremities.append(
                    RouteWireExtremity(
                        connector_occurrence_id=connector_info["connector_occurrence_id"],
                        contact_point_id=contact_point.id,
                        cavity_id=contact_point.cavity.id,
                        cavity_number=contact_point.cavity.cavity_number,
                        terminal_type=str(contact_point.terminal.terminal_type),
                    )
                )

            steps.append(
                ProcessStep(
                    step_id=self._next_step_id(harness_id, "route_wire"),
                    sequence_number=self._next_sequence(),
                    process_type=ProcessType.ROUTE_WIRE,
                    harness_id=harness_id,
                    station_id=station_id,
                    description=(
                        f"Route wire {wire_occurrence.id} "
                        f"(connection {connection.id})"
                    ),
                    parameters=RouteWireParameters(
                        connection_id=connection.id,
                        wire_occurrence_id=wire_occurrence.id,
                        wire_part_number=wire_occurrence.wire.part_number,
                        ordered_segment_ids=[
                            segment.id for segment in connection.segments
                        ],
                        ordered_peg_ids=ordered_peg_ids,
                        extremities=extremities,
                    ),
                )
            )

        return steps

    def _generate_protection_and_fixing(
        self, harness_input: HarnessInput
    ) -> List[ProcessStep]:
        """Generate APPLY_WIRE_PROTECTION and APPLY_FIXING steps."""
        steps: List[ProcessStep] = []
        harness = harness_input.harness
        station_id = harness_input.station_id
        harness_id = harness.id

        # APPLY_WIRE_PROTECTION: from protection areas on segments
        for segment in harness.segments:
            for protection_area in segment.protection_areas:
                wire_protection_occ = protection_area.wire_protection_occurrence
                steps.append(
                    ProcessStep(
                        step_id=self._next_step_id(harness_id, "apply_protection"),
                        sequence_number=self._next_sequence(),
                        process_type=ProcessType.APPLY_WIRE_PROTECTION,
                        harness_id=harness_id,
                        station_id=station_id,
                        description=(
                            f"Apply {wire_protection_occ.protection.protection_type or 'protection'} "
                            f"on segment {segment.id}"
                        ),
                        parameters=ApplyWireProtectionParameters(
                            wire_protection_occurrence_id=wire_protection_occ.id,
                            segment_id=segment.id,
                            start_location=protection_area.start_location,
                            end_location=protection_area.end_location,
                            protection_type=(
                                wire_protection_occ.protection.protection_type or ""
                            ),
                            part_number=wire_protection_occ.protection.part_number,
                        ),
                    )
                )

        # APPLY_FIXING: from fixing occurrences
        for fixing_occurrence in harness.fixing_occurrences:
            steps.append(
                ProcessStep(
                    step_id=self._next_step_id(harness_id, "apply_fixing"),
                    sequence_number=self._next_sequence(),
                    process_type=ProcessType.APPLY_FIXING,
                    harness_id=harness_id,
                    station_id=station_id,
                    description=(
                        f"Apply fixing {fixing_occurrence.id}"
                    ),
                    parameters=ApplyFixingParameters(
                        fixing_occurrence_id=fixing_occurrence.id,
                        # CDM does not map fixings to segments yet.
                        segment_id=None,
                        fixing_type=fixing_occurrence.fixing.fixing_type or "",
                        part_number=fixing_occurrence.fixing.part_number,
                    ),
                )
            )

        return steps

    def _generate_finalization(
        self, harness_input: HarnessInput
    ) -> List[ProcessStep]:
        """Generate REMOVE_HARNESS step."""
        harness_id = harness_input.harness.id
        station_id = harness_input.station_id

        return [
            ProcessStep(
                step_id=self._next_step_id(harness_id, "remove_harness"),
                sequence_number=self._next_sequence(),
                process_type=ProcessType.REMOVE_HARNESS,
                harness_id=harness_id,
                station_id=station_id,
                description=f"Remove completed harness {harness_id} from the board",
                parameters=RemoveHarnessParameters(harness_id=harness_id),
            )
        ]

    # ======================================================================
    # Phase assembly
    # ======================================================================

    @staticmethod
    def _assemble_phases(
        board_setup_steps: List[ProcessStep],
        wire_routing_steps: List[ProcessStep],
        protection_steps: List[ProcessStep],
        finalization_steps: List[ProcessStep],
    ) -> List[AssemblyPhase]:
        """Assemble all steps into ordered phases.

        Phase 4 (CONNECTOR_ASSEMBLY) is always included as an empty placeholder.
        """
        phases: List[AssemblyPhase] = []

        if board_setup_steps:
            phases.append(
                AssemblyPhase(
                    phase_type=PhaseType.BOARD_SETUP,
                    phase_label="Board Setup",
                    steps=board_setup_steps,
                )
            )

        if wire_routing_steps:
            phases.append(
                AssemblyPhase(
                    phase_type=PhaseType.WIRE_ROUTING,
                    phase_label="Wire Routing",
                    steps=wire_routing_steps,
                )
            )

        if protection_steps:
            phases.append(
                AssemblyPhase(
                    phase_type=PhaseType.PROTECTION_AND_FIXING,
                    phase_label="Protection and Fixing",
                    steps=protection_steps,
                )
            )

        # Connector Assembly -- always present as placeholder
        phases.append(
            AssemblyPhase(
                phase_type=PhaseType.CONNECTOR_ASSEMBLY,
                phase_label="Connector Assembly (placeholder)",
                steps=[],
            )
        )

        if finalization_steps:
            phases.append(
                AssemblyPhase(
                    phase_type=PhaseType.FINALIZATION,
                    phase_label="Finalization",
                    steps=finalization_steps,
                )
            )

        return phases

    # ======================================================================
    # Peg ordering along a wire route
    # ======================================================================

    def _compute_ordered_peg_ids(
        self,
        segments: List[Segment],
        segment_pegs_map: Dict[str, List[PegPosition]],
    ) -> List[str]:
        """Compute ordered peg IDs along a multi-segment wire path.

        For each segment in the route, finds all pegs on that segment
        and orders them by their parametric position along the segment
        (taking traversal direction into account).
        """
        if not segments:
            return []

        directions = self._determine_segment_directions(segments)
        ordered_peg_ids: List[str] = []

        for segment, is_forward in zip(segments, directions):
            pegs_on_segment = segment_pegs_map.get(segment.id, [])
            if not pegs_on_segment:
                continue

            # Compute parametric position for each peg along the segment
            pegs_with_parameter: List[Tuple[float, PegPosition]] = []
            for peg in pegs_on_segment:
                parametric_value = self._compute_parametric_position(
                    peg.position.x, peg.position.y, segment
                )
                pegs_with_parameter.append((parametric_value, peg))

            # Sort: ascending if forward traversal, descending if reversed
            pegs_with_parameter.sort(
                key=lambda item: item[0], reverse=(not is_forward)
            )

            ordered_peg_ids.extend(
                peg.id for _, peg in pegs_with_parameter
            )

        return ordered_peg_ids

    @staticmethod
    def _compute_parametric_position(
        peg_x: float, peg_y: float, segment: Segment
    ) -> float:
        """Compute 0.0-1.0 parametric position of a point along a segment.

        Projects the peg position onto the line from start_node to end_node.
        """
        start_x = segment.start_node.position.coord_x
        start_y = segment.start_node.position.coord_y
        end_x = segment.end_node.position.coord_x
        end_y = segment.end_node.position.coord_y

        direction_x = end_x - start_x
        direction_y = end_y - start_y
        length_squared = direction_x ** 2 + direction_y ** 2

        if length_squared == 0.0:
            return 0.0

        # Dot product of (peg - start) with direction, normalized
        relative_x = peg_x - start_x
        relative_y = peg_y - start_y
        parametric_value = (
            relative_x * direction_x + relative_y * direction_y
        ) / length_squared

        return max(0.0, min(1.0, parametric_value))

    @staticmethod
    def _determine_segment_directions(segments: List[Segment]) -> List[bool]:
        """Determine traversal direction for each segment in a path.

        Returns a list of booleans: True = forward (start->end),
        False = reversed (end->start).
        """
        if not segments:
            return []

        if len(segments) == 1:
            return [True]

        directions: List[Optional[bool]] = [None] * len(segments)

        # First two segments: find shared node
        seg_0_nodes = {segments[0].start_node.id, segments[0].end_node.id}
        seg_1_nodes = {segments[1].start_node.id, segments[1].end_node.id}
        shared_nodes = seg_0_nodes & seg_1_nodes

        if shared_nodes:
            shared_node_id = shared_nodes.pop()
            # seg_0 is traversed towards the shared node
            directions[0] = segments[0].end_node.id == shared_node_id
            # seg_1 is traversed away from the shared node
            directions[1] = segments[1].start_node.id == shared_node_id
        else:
            directions[0] = True
            directions[1] = True

        # Continue for remaining segments by chaining
        for index in range(2, len(segments)):
            previous_segment = segments[index - 1]
            current_segment = segments[index]

            # Exit node of previous segment
            if directions[index - 1]:
                previous_exit_node_id = previous_segment.end_node.id
            else:
                previous_exit_node_id = previous_segment.start_node.id

            # Current segment should enter from previous exit
            if current_segment.start_node.id == previous_exit_node_id:
                directions[index] = True
            elif current_segment.end_node.id == previous_exit_node_id:
                directions[index] = False
            else:
                directions[index] = True  # Fallback

        return [d if d is not None else True for d in directions]

    # ======================================================================
    # Helpers
    # ======================================================================

    @staticmethod
    def _build_contact_point_lookup(
        connector_occurrences: List[ConnectorOccurrence],
    ) -> Dict[str, Dict]:
        """Build contact_point_id -> {connector_occurrence_id, cavity_number}."""
        lookup: Dict[str, Dict] = {}
        for connector_occurrence in connector_occurrences:
            for contact_point in connector_occurrence.contact_points:
                lookup[contact_point.id] = {
                    "connector_occurrence_id": connector_occurrence.id,
                    "cavity_number": contact_point.cavity.cavity_number,
                }
        return lookup

    @staticmethod
    def _build_segment_pegs_map(
        pegs: List[PegPosition],
    ) -> Dict[str, List[PegPosition]]:
        """Build segment_id -> list of pegs map."""
        segment_pegs_map: Dict[str, List[PegPosition]] = {}
        for peg in pegs:
            if peg.segment_id not in segment_pegs_map:
                segment_pegs_map[peg.segment_id] = []
            segment_pegs_map[peg.segment_id].append(peg)
        return segment_pegs_map

    def _next_sequence(self) -> int:
        """Return the next global sequence number."""
        self._sequence_counter += 1
        return self._sequence_counter

    def _next_step_id(self, harness_id: str, step_type: str) -> str:
        """Generate a unique step ID."""
        return f"{harness_id}_{step_type}_{self._sequence_counter + 1:04d}"
