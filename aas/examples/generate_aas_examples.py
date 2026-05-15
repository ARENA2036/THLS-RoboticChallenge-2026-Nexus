"""
End-to-end AAS example generator.

Runs the full pipeline for a CDM example harness:
  1. Load CDM WireHarness from JSON
  2. Generate board layout (LayoutGeneratorService)
  3. Generate Bill of Process (BoPGeneratorService)
  4. Load simulation config (ConfigLoader)
  5. Build all AAS shells via builders
  6. Serialize to JSON files in aas/examples/output/

Usage:
    python3 aas/examples/generate_aas_examples.py

Outputs (in aas/examples/output/):
    wire_harness_aas.json           — WireHarnessAAS (1 shell, 3 submodels)
    component_aas.json              — all ComponentAAS shells (N shells, 2N submodels)
    assembly_station_aas.json       — AssemblyStationAAS (1 shell, 3 submodels)
    bill_of_process_aas.json        — BillOfProcessAAS (1 shell, 2 submodels)
    assembly_board_layout_aas.json  — AssemblyBoardLayoutAAS (1 shell, 2 submodels)
    material_delivery_aas.json      — MaterialDeliveryAAS (1 shell, 2 submodels)
    workspace_zones_aas.json        — WorkspaceZonesAAS (1 shell, 2 submodels)
    execution_trace_aas.json        — ExecutionTraceAAS (1 shell, 2 submodels)
    prefab_bop_aas.json             — PreFabBillOfProcessAAS (1 shell, 2 submodels)
    production_order_aas.json       — ProductionOrderAAS (1 shell, 2 submodels)
"""

import json
import sys
from pathlib import Path

# Make project root importable
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from public.cdm.definitions.cdm_schema import WireHarness
from public.cdm.examples import load_example
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import LayoutRequest, BoardConfig, LayoutParameters
from bill_of_process.BoPConfig import BoPGeneratorConfig, HarnessInput
from bill_of_process.BoPGeneratorService import BoPGeneratorService
from simulation.core.ConfigLoader import ConfigLoader

from aas.builders.cdm_to_aas import build_aas_from_harness
from aas.builders.config_to_aas import build_aas_from_config
from aas.builders.bop_to_aas import build_aas_from_bop
from aas.builders.layout_to_aas import build_aas_from_layout
from aas.builders.delivery_to_aas import build_aas_from_delivery_config
from aas.builders.workspace_to_aas import build_aas_from_workspace
from aas.builders.trace_to_aas import build_aas_from_trace
from aas.builders.prefab_to_aas import build_aas_from_prefab
from aas.builders.order_to_aas import build_aas_from_order
from aas.submodels.execution_trace import StepOutcome, RobotTrace
from aas.serializer import write_aas_json, summarize_store

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SIMULATION_ROOT = _root / "simulation"
STATION_ID = "station_01"


def compute_board_config(harness: WireHarness) -> BoardConfig:
    if harness.nodes:
        all_x = [n.position.coord_x for n in harness.nodes]
        all_y = [n.position.coord_y for n in harness.nodes]
        padding = 150.0
        board_width = max(max(all_x) - min(all_x) + 2 * padding, 600.0)
        board_height = max(max(all_y) - min(all_y) + 2 * padding, 400.0)
        return BoardConfig(
            width_mm=board_width,
            height_mm=board_height,
            offset_x=-min(all_x) + padding,
            offset_y=-min(all_y) + padding,
        )
    return BoardConfig()


def _make_mock_trace(bill_of_process, robots_config):
    """Create synthetic execution outcomes for the example trace AAS."""
    from aas.submodels.execution_trace import TcpWaypoint
    step_outcomes = []
    total_time = 0.0
    for phase in bill_of_process.phases:
        for step in phase.steps:
            duration = 3.5
            step_outcomes.append(StepOutcome(
                step_id=step.step_id,
                process_type=step.process_type.value,
                success=True,
                start_time_s=total_time,
                end_time_s=total_time + duration,
                executed_ticks=int(duration * 500),
            ))
            total_time += duration

    robot_traces = []
    for robot_def in robots_config.robots:
        waypoints = [
            TcpWaypoint(
                timestamp_s=i * 0.5,
                position_m=[0.3 + i * 0.01, 0.0, 0.5],
                quat_wxyz=[1.0, 0.0, 0.0, 0.0],
            )
            for i in range(5)
        ]
        robot_traces.append(RobotTrace(
            robot_name=robot_def.robot_name,
            tcp_waypoints=waypoints,
        ))

    return step_outcomes, robot_traces, total_time


def main() -> None:
    print("Loading CDM example 'simple'...")
    harness = load_example("simple")
    print(f"  Harness: {harness.part_number}  ({len(harness.connector_occurrences)} connectors, "
          f"{len(harness.wire_occurrences)} wires)")

    # --- Layout ---
    print("Generating layout...")
    layout_service = LayoutGeneratorService()
    board_config = compute_board_config(harness)
    layout_response = layout_service.generate_layout(
        LayoutRequest(
            harness=harness,
            board_config=board_config,
            parameters=LayoutParameters(
                default_peg_interval_mm=250.0,
                connector_inward_offset_mm=30.0,
                connector_buffer_zone_mm=50.0,
                merge_distance_mm=80.0,
            ),
        )
    )
    print(f"  Layout: {layout_response.metrics.total_pegs} pegs, "
          f"{layout_response.metrics.total_holders} holders")

    # --- BoP ---
    print("Generating Bill of Process...")
    bop_config = BoPGeneratorConfig(
        production_id="example_production_001",
        harness_inputs=[
            HarnessInput(
                harness=harness,
                layout_response=layout_response,
                station_id=STATION_ID,
                cdm_source="public/cdm/examples/simple_harness.json",
            )
        ],
    )
    bop_service = BoPGeneratorService()
    bill_of_process = bop_service.generate(bop_config)
    total_steps = sum(len(p.steps) for p in bill_of_process.phases)
    print(f"  BoP: {len(bill_of_process.phases)} phases, {total_steps} steps")

    # --- Simulation config ---
    print("Loading simulation config...")
    config_loader = ConfigLoader(str(SIMULATION_ROOT))
    station_config = config_loader.load_station_config()
    robots_config = config_loader.load_robots_config()
    grippers_config = config_loader.load_grippers_config()
    scene_objects_config = config_loader.load_scene_objects_config()
    board_setup_config = config_loader.load_board_setup_config()
    wire_routing_config = config_loader.load_wire_routing_config()
    print(f"  Station board: {station_config.board.length_m}m × {station_config.board.width_m}m, "
          f"{len(robots_config.robots)} robots")

    # =========================================================================
    # Build AAS objects — original 4 shells
    # =========================================================================

    print("\nBuilding AAS shells (original 4)...")

    print("  Building WireHarnessAAS + ComponentAAS...")
    cdm_result = build_aas_from_harness(harness)

    print("  Building AssemblyStationAAS...")
    station_bundle = build_aas_from_config(
        station_id=STATION_ID,
        station_config=station_config,
        robots_config=robots_config,
        grippers_config=grippers_config,
        scene_objects_config=scene_objects_config,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
    )

    print("  Building BillOfProcessAAS...")
    bop_bundle = build_aas_from_bop(bill_of_process)

    # =========================================================================
    # Build AAS objects — 6 new shells
    # =========================================================================

    print("\nBuilding AAS shells (6 new)...")

    print("  Building AssemblyBoardLayoutAAS...")
    layout_bundle = build_aas_from_layout(
        harness_id=harness.id,
        layout_response=layout_response,
        board_config=board_config,
        harness_part_number=harness.part_number or "",
    )

    print("  Building MaterialDeliveryAAS...")
    delivery_bundle = build_aas_from_delivery_config(
        station_id=STATION_ID,
        board_setup_config=board_setup_config,
        wire_routing_config=wire_routing_config,
    )

    print("  Building WorkspaceZonesAAS...")
    workspace_bundle = build_aas_from_workspace(
        station_id=STATION_ID,
        robots_config=robots_config,
        station_config=station_config,
        board_setup_config=board_setup_config,
    )

    print("  Building ExecutionTraceAAS (mock trace)...")
    step_outcomes, robot_traces, sim_end_time = _make_mock_trace(bill_of_process, robots_config)
    trace_bundle = build_aas_from_trace(
        production_id=bill_of_process.production_id,
        overall_success=True,
        total_steps=total_steps,
        successful_steps=total_steps,
        start_time_s=0.0,
        end_time_s=sim_end_time,
        step_outcomes=step_outcomes,
        robot_traces=robot_traces,
    )

    print("  Building PreFabBillOfProcessAAS...")
    prefab_bundle = build_aas_from_prefab(harness)

    print("  Building ProductionOrderAAS...")
    harness_global_asset_id = f"urn:NEXUS:harness:{harness.part_number}:{harness.id}"
    bop_global_asset_id = f"urn:NEXUS:bop:{bill_of_process.production_id}"
    station_global_asset_id = f"urn:NEXUS:station:{STATION_ID}"
    order_bundle = build_aas_from_order(
        order_number="PO-2026-001",
        production_quantity=10,
        target_delivery_date="2026-12-31",
        status="PLANNED",
        harness_variant_asset_ids=[harness_global_asset_id],
        bop_asset_id=bop_global_asset_id,
        station_asset_id=station_global_asset_id,
        notes="Example production order for the simple harness variant.",
    )

    # =========================================================================
    # Serialize to JSON
    # =========================================================================

    print(f"\nSerializing to {OUTPUT_DIR}/...")

    def _write(filename: str, *bundles, label: str = "") -> None:
        out = OUTPUT_DIR / filename
        store = write_aas_json(out, *bundles)
        summary = summarize_store(store)
        tag = f"  [{label}] " if label else "  "
        print(f"{tag}{out.name}: {summary['shells']} shells, {summary['submodels']} submodels")

    # Original 4
    _write("wire_harness_aas.json", cdm_result.wire_harness_bundle, label="Product")
    _write("component_aas.json", *cdm_result.component_bundles, label="Component")
    _write("assembly_station_aas.json", station_bundle, label="Resource")
    _write("bill_of_process_aas.json", bop_bundle, label="Process")

    # New 6
    _write("assembly_board_layout_aas.json", layout_bundle, label="Layout")
    _write("material_delivery_aas.json", delivery_bundle, label="Delivery")
    _write("workspace_zones_aas.json", workspace_bundle, label="Workspace")
    _write("execution_trace_aas.json", trace_bundle, label="Trace")
    _write("prefab_bop_aas.json", prefab_bundle, label="PreFab")
    _write("production_order_aas.json", order_bundle, label="Order")

    print("\nDone.")


if __name__ == "__main__":
    main()
