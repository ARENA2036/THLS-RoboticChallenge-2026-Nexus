#!/usr/bin/env python3
"""
Generate Bill of Process (BoP) examples from CDM harness examples.

This script:
    1. Loads each CDM example harness (simple, medium, complex)
    2. Runs the layout generator to compute peg and holder positions
    3. Feeds the WireHarness + LayoutResponse into the BoPGeneratorService
    4. Saves the resulting ProductionBillOfProcess as pretty-printed JSON
    5. Prints a summary of phases, step counts, and wire routing order
"""

import json
import sys
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from bill_of_process.BoPModels import (
    PhaseType,
    ProductionBillOfProcess,
    RouteWireParameters,
)
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import (
    BoardConfig,
    LayoutParameters,
    LayoutRequest,
    LayoutResponse,
    WireHarness,
)
from public.cdm.examples import list_examples, load_example


OUTPUT_DIR = Path(__file__).parent


def compute_board_config(harness: WireHarness) -> BoardConfig:
    """Compute a BoardConfig that fits the harness with padding.

    Reuses the same sizing logic as layout_generator/examples/sample_usage.py.
    """
    if harness.nodes:
        all_x = [node.position.coord_x for node in harness.nodes]
        all_y = [node.position.coord_y for node in harness.nodes]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        padding = 150.0
        board_width = max(max_x + padding, max_x - min_x + 2 * padding, 600.0)
        board_height = max(max_y + padding, max_y - min_y + 2 * padding, 400.0)

        offset_x = -min_x + padding
        offset_y = -min_y + padding
    else:
        board_width, board_height = 1200.0, 800.0
        offset_x, offset_y = 0.0, 0.0

    return BoardConfig(
        width_mm=board_width,
        height_mm=board_height,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def generate_layout(
    harness: WireHarness,
    layout_service: LayoutGeneratorService,
) -> LayoutResponse:
    """Run the layout generator for a harness."""
    board_config = compute_board_config(harness)
    parameters = LayoutParameters(
        default_peg_interval_mm=250.0,
        connector_inward_offset_mm=30.0,
        connector_buffer_zone_mm=50.0,
        merge_distance_mm=80.0,
    )
    request = LayoutRequest(
        harness=harness,
        board_config=board_config,
        parameters=parameters,
    )
    return layout_service.generate_layout(request)


def generate_bop(
    example_name: str,
    harness: WireHarness,
    layout_response: LayoutResponse,
) -> ProductionBillOfProcess:
    """Generate a BoP for a single harness."""
    config = BoPGeneratorConfig(
        production_id=f"example_{example_name}",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_response,
                station_id="assembly_station_1",
                cdm_source=f"public/cdm/examples/{example_name}_harness.json",
            )
        ],
    )
    service = BoPGeneratorService()
    return service.generate(config)


def save_bop(bop: ProductionBillOfProcess, filename: str) -> Path:
    """Save a BoP to JSON file."""
    filepath = OUTPUT_DIR / filename
    data = bop.model_dump(mode="json")
    with open(filepath, "w") as output_file:
        json.dump(data, output_file, indent=2)
    return filepath


def print_bop_summary(
    example_name: str, harness: WireHarness, bop: ProductionBillOfProcess
) -> None:
    """Print a human-readable summary of the generated BoP."""
    separator = "=" * 60

    print(f"\n{separator}")
    print(f"  BoP: {example_name}")
    print(f"{separator}")

    print(f"\n  Harness: {harness.id} ({harness.part_number})")
    print(f"    Connectors:  {len(harness.connector_occurrences)}")
    print(f"    Wires:       {len(harness.wire_occurrences)}")
    print(f"    Connections: {len(harness.connections)}")
    print(f"    Segments:    {len(harness.segments)}")

    print(f"\n  Production ID: {bop.production_id}")
    print(f"  Station:       {bop.harness_refs[0].station_id}")

    total_steps = 0
    print(f"\n  Phases:")
    for phase in bop.phases:
        step_count = len(phase.steps)
        total_steps += step_count
        print(f"    {phase.phase_type.value:<28s}  {step_count:>3d} steps  ({phase.phase_label})")

        # Break down by process type within phase
        process_type_counts: dict[str, int] = {}
        for step in phase.steps:
            process_type_value = step.process_type.value
            process_type_counts[process_type_value] = (
                process_type_counts.get(process_type_value, 0) + 1
            )
        for process_type_name, count in sorted(process_type_counts.items()):
            print(f"      - {process_type_name}: {count}")

    print(f"\n  Total steps: {total_steps}")

    # Wire routing order
    routing_phase = next(
        (phase for phase in bop.phases if phase.phase_type == PhaseType.WIRE_ROUTING),
        None,
    )
    if routing_phase and routing_phase.steps:
        print(f"\n  Wire Routing Order ({len(routing_phase.steps)} wires):")
        for index, step in enumerate(routing_phase.steps, start=1):
            params = step.parameters
            if isinstance(params, RouteWireParameters):
                extremity_summary = " -> ".join(
                    f"{ext.connector_occurrence_id}[cav {ext.cavity_number}]"
                    for ext in params.extremities
                )
                print(
                    f"    {index:>3d}. {params.wire_part_number:<20s}  "
                    f"{params.connection_id:<12s}  {extremity_summary}"
                )

    print()


def main() -> None:
    """Generate BoP examples for all available CDM harnesses."""
    print("=" * 60)
    print("  Bill of Process -- Example Generator")
    print("=" * 60)

    layout_service = LayoutGeneratorService()
    example_names = list_examples()
    generated_files: list[Path] = []

    for example_name in example_names:
        print(f"\n[{example_name}] Loading CDM harness...")
        harness = load_example(example_name)

        print(f"[{example_name}] Running layout generator...")
        layout_response = generate_layout(harness, layout_service)
        print(
            f"[{example_name}] Layout: {layout_response.metrics.total_pegs} pegs, "
            f"{layout_response.metrics.total_holders} holders"
        )

        print(f"[{example_name}] Generating Bill of Process...")
        bop = generate_bop(example_name, harness, layout_response)

        filename = f"{example_name}_bop.json"
        filepath = save_bop(bop, filename)
        generated_files.append(filepath)
        print(f"[{example_name}] Saved: {filepath}")

        print_bop_summary(example_name, harness, bop)

    print("=" * 60)
    print("  All examples generated!")
    print("=" * 60)
    print(f"\n  Output directory: {OUTPUT_DIR}")
    for filepath in generated_files:
        print(f"    - {filepath.name}")
    print()


if __name__ == "__main__":
    main()
