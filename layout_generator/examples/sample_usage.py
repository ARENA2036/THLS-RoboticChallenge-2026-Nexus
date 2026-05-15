#!/usr/bin/env python3
"""
Sample Usage Script for the Layout Generator Module

This script demonstrates how to:
1. Load wire harness CDMs from example files
2. Generate board layouts (pegs and connector holders)
3. Visualize the results
4. Export to PNG/SVG
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from public.cdm.examples import list_examples, load_example

from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import (
    BoardConfig,
    LayoutParameters,
    LayoutRequest,
    WireHarness,
)
from layout_generator.visualizer import BoardLayoutVisualizer


def process_harness(
    harness: WireHarness,
    name: str,
    output_dir: Path,
    service: LayoutGeneratorService,
) -> None:
    """
    Process a single harness: generate layout and visualize.

    Args:
        harness: WireHarness to process
        name: Name for output files
        output_dir: Directory to save output files
        service: Layout generator service instance
    """
    print(f"\n{'=' * 60}")
    print(f"Processing: {name}")
    print(f"{'=' * 60}")

    # Print harness info
    print("\n[1] Harness Details:")
    print(f"    - ID: {harness.id}")
    print(f"    - Part Number: {harness.part_number}")
    print(f"    - Nodes: {len(harness.nodes)}")
    print(f"    - Segments: {len(harness.segments)}")
    print(f"    - Connectors: {len(harness.connector_occurrences)}")
    print(f"    - Wires: {len(harness.wire_occurrences)}")
    print(f"    - Connections: {len(harness.connections)}")

    # Calculate board size based on harness extent
    if harness.nodes:
        all_x = [node.position.coord_x for node in harness.nodes]
        all_y = [node.position.coord_y for node in harness.nodes]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        padding = 150.0

        # Board must be large enough to contain all nodes plus padding
        # Consider both the spread and the absolute positions
        board_width = max(max_x + padding, max_x - min_x + 2 * padding, 600.0)
        board_height = max(max_y + padding, max_y - min_y + 2 * padding, 400.0)

        # Apply offset to center the harness on the board
        # Offset moves harness content so min coordinates start at padding
        offset_x = -min_x + padding
        offset_y = -min_y + padding
    else:
        board_width, board_height = 1200.0, 800.0
        offset_x, offset_y = 0.0, 0.0

    board_config = BoardConfig(
        width_mm=board_width,
        height_mm=board_height,
        offset_x=offset_x,
        offset_y=offset_y,
    )

    parameters = LayoutParameters(
        default_peg_interval_mm=250.0,
        intersection_offset_mm=30.0,
        connector_inward_offset_mm=30.0,
        connector_buffer_zone_mm=50.0,
        merge_distance_mm=80.0,
    )

    print("\n[2] Board Configuration:")
    print(f"    - Size: {board_config.width_mm:.0f} x {board_config.height_mm:.0f} mm")
    print(f"    - Offset: ({board_config.offset_x:.0f}, {board_config.offset_y:.0f})")
    print(f"    - Intersection offset: {parameters.intersection_offset_mm:.0f} mm")

    # Generate layout
    print("\n[3] Generating Layout...")
    request = LayoutRequest(
        harness=harness,
        board_config=board_config,
        parameters=parameters,
    )

    response = service.generate_layout(request)

    print(f"    - Connector holders: {response.metrics.total_holders}")
    print(f"    - Pegs placed: {response.metrics.total_pegs}")
    print(f"      - Breakout pegs: {response.metrics.breakout_pegs}")
    print(f"      - Interval pegs: {response.metrics.interval_pegs}")
    print(f"    - Merged positions: {response.metrics.merged_positions}")
    print(f"    - Board utilization: {response.metrics.board_utilization_percent:.1f}%")

    # Print connector holders
    print("\n    Connector Holders:")
    for holder in response.connector_holders:
        print(f"      - {holder.connector_id}: ({holder.position.x:.1f}, {holder.position.y:.1f}) "
              f"@ {holder.orientation_deg:.1f}° [{holder.holder_type.value}]")

    # Create visualization
    print("\n[4] Creating Visualization...")
    visualizer = BoardLayoutVisualizer(board_config)
    visualizer.add_harness(harness)
    visualizer.add_layout(response)

    visualizer.render(
        show_grid=True,
        show_forbidden_zones=True,
        show_labels=True,
        show_buffer_zones=True,
        show_individual_wires=True,
    )

    # Export
    png_path = output_dir / f"{name}_layout.png"
    svg_path = output_dir / f"{name}_layout.svg"

    print("\n[5] Exporting...")
    visualizer.export_png(str(png_path), dpi=150)
    print(f"    - PNG: {png_path}")

    visualizer.export_svg(str(svg_path))
    print(f"    - SVG: {svg_path}")

    visualizer.close()


def main():
    """Main entry point for the sample usage demo."""
    print("=" * 60)
    print("Layout Generator - Example CDM Processing")
    print("=" * 60)

    # Get output directory
    output_dir = Path(__file__).parent

    # Initialize service
    service = LayoutGeneratorService()

    # Get list of available examples
    examples = list_examples()
    print(f"\nAvailable examples: {examples}")

    # Process each example
    for example_name in examples:
        print(f"\nLoading example: {example_name}")
        harness = load_example(example_name)
        process_harness(harness, example_name, output_dir, service)

    print("\n" + "=" * 60)
    print("All examples processed!")
    print("=" * 60)

    # Summary
    print(f"\nOutput files generated in: {output_dir}")
    for example_name in examples:
        print(f"  - {example_name}_layout.png")
        print(f"  - {example_name}_layout.svg")


if __name__ == "__main__":
    main()
