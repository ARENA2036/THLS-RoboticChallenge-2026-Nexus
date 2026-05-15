# 🌐 Asset Administration Shell (AAS)

> [!IMPORTANT]
> The **Asset Administration Shell (AAS)** serves as the information backbone of the NEXUS project. It provides a standardized framework for semantic modeling, structured representation, and interoperable access to asset-related data across the entire lifecycle of the robotic assembly system.

This module implements the data serialization layer, converting the core models — CDM, Resource Modeling, and Bill of Process — into IDTA-compliant AAS shells with real semantic IRIs. It utilizes the [basyx-python-sdk](https://github.com/eclipse-basyx/basyx-python-sdk) for serialization to IDTA AAS v3 JSON.

---

## Background

The paper *"From Design to Action: Enabling End-to-End Robotic Wire Harness Assembly"* proposes the AAS as the information middleware connecting the three PPR dimensions:

| PPR dimension | Data model (existing) | AAS shell (this module) |
|---|---|---|
| **Product** | `WireHarness` (CDM) | `WireHarnessAAS` + `ComponentAAS` |
| **Resource** | `StationConfig`, `RobotsConfig`, … | `AssemblyStationAAS` |
| **Process** | `ProductionBillOfProcess` | `BillOfProcessAAS` |

---

## Asset types

### Overview

| AAS | PPR | GlobalAssetId | Submodels | Source |
|---|---|---|---|---|
| `WireHarnessAAS` | Product | `urn:NEXUS:harness:{pn}:{id}` | DigitalNameplate · HierarchicalBOM · CDMTopology | `WireHarness` (CDM) |
| `ComponentAAS` | Product | `urn:NEXUS:component:{type}:{pn}` | DigitalNameplate · TechnicalProperties | CDM component definitions |
| `AssemblyStationAAS` | Resource | `urn:NEXUS:station:{id}` | DigitalNameplate · CapabilityDescription · WorkcellConfiguration | `StationConfig`, `RobotsConfig`, … |
| `BillOfProcessAAS` | Process | `urn:NEXUS:bop:{id}` | DigitalNameplate · ProcessParametersType | `ProductionBillOfProcess` |
| `AssemblyBoardLayoutAAS` | Resource | `urn:NEXUS:layout:{harness_id}` | DigitalNameplate · AssemblyBoardLayout | `LayoutResponse` |
| `MaterialDeliveryAAS` | Resource | `urn:NEXUS:delivery:{station_id}` | DigitalNameplate · MaterialDelivery | `BoardSetupConfig`, `WireRoutingConfig` |
| `WorkspaceZonesAAS` | Resource | `urn:NEXUS:workspace:{station_id}` | DigitalNameplate · WorkspaceZones | `RobotsConfig`, `StationConfig` |
| `ExecutionTraceAAS` | Process | `urn:NEXUS:trace:{production_id}` | DigitalNameplate · ExecutionTrace | `RobotFeedback`, `TickResult` |
| `PreFabBillOfProcessAAS` | Process | `urn:NEXUS:prefab:{harness_id}` | DigitalNameplate · PreFabBillOfProcess | `WireHarness` (CDM) |
| `ProductionOrderAAS` | Process | `urn:NEXUS:order:{order_number}` | DigitalNameplate · ProductionOrder | order parameters (ERP) |

---

### WireHarnessAAS — Product (one per `WireHarness`)
`GlobalAssetId: urn:NEXUS:harness:{part_number}:{harness_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Manufacturer, part number, description, version, date |
| HierarchicalBOM | IDTA 02011-1-1 | Full BOM tree; each occurrence node carries a `SameAs` reference to the corresponding ComponentAAS |
| CDMTopology | custom `urn:NEXUS:submodel:CDMTopology:1-0` | Nodes, Segments (with lengths, Bezier curves, protection areas), Connections (wire→pin routing), Routings |

### ComponentAAS — Tier-2 supplier (one per unique component definition)
`GlobalAssetId: urn:NEXUS:component:{type}:{part_number}`

Covers all six CDM component classes: `Connector`, `Wire`, `Terminal`, `WireProtection`, `Accessory`, `Fixing`.

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Part number, manufacturer, description, product family |
| TechnicalProperties | custom `urn:NEXUS:submodel:TechnicalProperties:1-0` | Type-specific: connector slots/cavities; wire cross-section/material/colors/cores; terminal gender/crimp range; protection/fixing types |

### AssemblyStationAAS — Resource (one per station)
`GlobalAssetId: urn:NEXUS:station:{station_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Station ID, robot count, gripper type |
| CapabilityDescription | IDTA 02020-1-0 | Six capabilities (PlacePeg, PlaceConnectorHolder, RouteWire, ApplyWireProtection, ApplyFixing, RemoveHarness), each with typed `CapabilityProperty` constraints |
| WorkcellConfiguration | custom `urn:NEXUS:submodel:WorkcellConfiguration:1-0` | Board dimensions & pose; 2× UR10e (base pose, joint limits, home angles); Robotiq 2F-85 grippers; peg shape catalog; board-setup and wire-routing parameters |

### BillOfProcessAAS — Process (one per production batch)
`GlobalAssetId: urn:NEXUS:bop:{production_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Production batch ID, creation date |
| ProcessParametersType | IDTA 02031-1-0 | Phases → Steps hierarchy. Each step carries: `ProcessType`, `HarnessId`, `StationId`, `SequenceNumber`, `DependsOn`, and a typed `Parameters` collection (one variant per process type) |

### AssemblyBoardLayoutAAS — Resource (one per harness layout)
`GlobalAssetId: urn:NEXUS:layout:{harness_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Harness ID, peg/holder counts |
| AssemblyBoardLayout | custom `urn:NEXUS:submodel:AssemblyBoardLayout:1-0` | BoardConfig (width/height/offset in mm), LayoutMetrics, Pegs SML (id, position, segment_id, reason, orientation_deg), ConnectorHolders SML (connector_id, position, holder_type, dimensions) |

### MaterialDeliveryAAS — Resource (one per station)
`GlobalAssetId: urn:NEXUS:delivery:{station_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Station ID, object/wire-end pickup counts |
| MaterialDelivery | custom `urn:NEXUS:submodel:MaterialDelivery:1-0` | BoardSetupParameters (approach/retreat/transport offsets, gripper values), ObjectPickups SML (peg/holder 3-D pickup poses), WireRoutingParameters, WireEndPickups SML (per-wire-end pose + crimp orientation), PullTestThresholds |

### WorkspaceZonesAAS — Resource (one per station)
`GlobalAssetId: urn:NEXUS:workspace:{station_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Station ID, robot count, safety policy |
| WorkspaceZones | custom `urn:NEXUS:submodel:WorkspaceZones:1-0` | BoardSplit (center X), PickupZone (clearance radius, mutual-exclusion policy), CoordinationPolicy (SafetyPolicy, MaxWaitTimeS, MaxRetryCount), RobotBoardHalves (per-robot: own half, base position, home angles), ZoneNames |

### ExecutionTraceAAS — Process (one per simulation run)
`GlobalAssetId: urn:NEXUS:trace:{production_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Production ID, overall success status |
| ExecutionTrace | custom `urn:NEXUS:submodel:ExecutionTrace:1-0` | ExecutionSummary (success flag, step counts, total duration), StepOutcomes SML (per step: process type, success, timing, executed ticks, errors), RobotTraces (per robot: sampled TCP path as TcpWaypoint SML, error log) |

### PreFabBillOfProcessAAS — Process (one per harness)
`GlobalAssetId: urn:NEXUS:prefab:{harness_id}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Harness ID/part number, wire occurrence count |
| PreFabBillOfProcess | custom `urn:NEXUS:submodel:PreFabBillOfProcess:1-0` | Three phases following OPC 40570: CutPhase (one step per wire occurrence → cut length, cross section), StripPhase (two steps per wire → strip length, conductor material), CrimpPhase (one step per terminal-connected extremity → terminal part number, crimp force) |

### ProductionOrderAAS — Process (one per production order)
`GlobalAssetId: urn:NEXUS:order:{order_number}`

| Submodel | IDTA template | Content |
|---|---|---|
| DigitalNameplate | IDTA 02006-2-0 | Order number, quantity, delivery date, status |
| ProductionOrder | custom `urn:NEXUS:submodel:ProductionOrder:1-0` | OrderNumber, ProductionQuantity, TargetDeliveryDate, Status (PLANNED / IN_PRODUCTION / COMPLETED / CANCELLED), HarnessVariants SML of ReferenceElements (→ WireHarnessAAS GlobalAssetIds), LinkedBillOfProcess, LinkedStation |

---

## File structure

```
aas/
├── semantic_ids.py              # Central registry of all IDTA and project IRIs
├── submodels/
│   ├── digital_nameplate.py         # IDTA 02006-2-0 builder
│   ├── hierarchical_bom.py          # IDTA 02011-1-1 builder
│   ├── cdm_topology.py              # Custom topology submodel builder
│   ├── capability_description.py    # IDTA 02020-1-0 builder
│   ├── workcell_configuration.py    # Custom workcell submodel builder
│   ├── process_parameters.py        # IDTA 02031-1-0 builder
│   ├── technical_properties.py      # Custom component technical properties builder
│   ├── assembly_board_layout.py     # Custom board layout submodel builder
│   ├── material_delivery.py         # Custom material delivery submodel builder
│   ├── workspace_zones.py           # Custom workspace zone submodel builder
│   ├── execution_trace.py           # Custom execution trace submodel builder
│   ├── prefab_process_parameters.py # Custom OPC 40570 pre-fab BoP builder
│   └── production_order.py          # Custom production order submodel builder
├── shells/
│   ├── wire_harness_aas.py          # Assembles WireHarnessAAS (3 submodels)
│   ├── assembly_station_aas.py      # Assembles AssemblyStationAAS (3 submodels)
│   ├── bill_of_process_aas.py       # Assembles BillOfProcessAAS (2 submodels)
│   ├── component_aas.py             # Assembles ComponentAAS (2 submodels)
│   ├── assembly_board_layout_aas.py # Assembles AssemblyBoardLayoutAAS (2 submodels)
│   ├── material_delivery_aas.py     # Assembles MaterialDeliveryAAS (2 submodels)
│   ├── workspace_zones_aas.py       # Assembles WorkspaceZonesAAS (2 submodels)
│   ├── execution_trace_aas.py       # Assembles ExecutionTraceAAS (2 submodels)
│   ├── prefab_bop_aas.py            # Assembles PreFabBillOfProcessAAS (2 submodels)
│   └── production_order_aas.py      # Assembles ProductionOrderAAS (2 submodels)
├── builders/
│   ├── cdm_to_aas.py           # WireHarness → WireHarnessAAS + [ComponentAAS]
│   ├── config_to_aas.py        # SimConfig objects → AssemblyStationAAS
│   ├── bop_to_aas.py           # ProductionBillOfProcess → BillOfProcessAAS
│   ├── layout_to_aas.py        # LayoutResponse → AssemblyBoardLayoutAAS
│   ├── delivery_to_aas.py      # BoardSetupConfig+WireRoutingConfig → MaterialDeliveryAAS
│   ├── workspace_to_aas.py     # RobotsConfig+StationConfig → WorkspaceZonesAAS
│   ├── trace_to_aas.py         # Execution results → ExecutionTraceAAS
│   ├── prefab_to_aas.py        # WireHarness → PreFabBillOfProcessAAS
│   └── order_to_aas.py         # Order parameters → ProductionOrderAAS
├── serializer.py               # write_aas_json() / summarize_store()
└── examples/
    └── generate_aas_examples.py  # End-to-end example → 10 JSON files
```

---

## Quick start

```bash
# Install dependency
pip install basyx-python-sdk

# Run the end-to-end example (from project root)
python3 aas/examples/generate_aas_examples.py
```

Output is written to `aas/examples/output/`:

| File | Shells | Submodels | Source |
|---|---|---|---|
| `wire_harness_aas.json` | 1 | 3 | CDM |
| `component_aas.json` | N | 2N | CDM component definitions |
| `assembly_station_aas.json` | 1 | 3 | SimulationConfig |
| `bill_of_process_aas.json` | 1 | 2 | ProductionBillOfProcess |
| `assembly_board_layout_aas.json` | 1 | 2 | LayoutResponse |
| `material_delivery_aas.json` | 1 | 2 | BoardSetupConfig + WireRoutingConfig |
| `workspace_zones_aas.json` | 1 | 2 | RobotsConfig + StationConfig |
| `execution_trace_aas.json` | 1 | 2 | mock trace (real: RobotFeedback + TickResult) |
| `prefab_bop_aas.json` | 1 | 2 | CDM (OPC 40570 Cut/Strip/Crimp) |
| `production_order_aas.json` | 1 | 2 | order parameters |

---

## Usage in code

```python
# Original 4 builders
from aas.builders.cdm_to_aas import build_aas_from_harness
from aas.builders.config_to_aas import build_aas_from_config
from aas.builders.bop_to_aas import build_aas_from_bop
from aas.serializer import write_aas_json

# New 6 builders
from aas.builders.layout_to_aas import build_aas_from_layout
from aas.builders.delivery_to_aas import build_aas_from_delivery_config
from aas.builders.workspace_to_aas import build_aas_from_workspace
from aas.builders.trace_to_aas import build_aas_from_trace
from aas.builders.prefab_to_aas import build_aas_from_prefab
from aas.builders.order_to_aas import build_aas_from_order

# Product AAS (harness must use layout-extended ConnectorOccurrence —
# use public.cdm.examples.load_example() or convert manually)
cdm_result = build_aas_from_harness(harness)

# Resource AAS — station
station_bundle = build_aas_from_config(
    station_id="station_01",
    station_config=station_config,
    robots_config=robots_config,
    grippers_config=grippers_config,
    scene_objects_config=scene_objects_config,
    board_setup_config=board_setup_config,
    wire_routing_config=wire_routing_config,
)

# Process AAS — assembly BoP
bop_bundle = build_aas_from_bop(bill_of_process)

# Resource AAS — board layout
layout_bundle = build_aas_from_layout(
    harness_id=harness.id,
    layout_response=layout_response,
    board_config=board_config,
)

# Resource AAS — material pickup positions
delivery_bundle = build_aas_from_delivery_config(
    station_id="station_01",
    board_setup_config=board_setup_config,
    wire_routing_config=wire_routing_config,
)

# Resource AAS — workspace zone coordination config
workspace_bundle = build_aas_from_workspace(
    station_id="station_01",
    robots_config=robots_config,
    station_config=station_config,
    board_setup_config=board_setup_config,
)

# Process AAS — simulation execution trace
from aas.submodels.execution_trace import StepOutcome, RobotTrace
trace_bundle = build_aas_from_trace(
    production_id="example_production_001",
    overall_success=True,
    total_steps=7,
    successful_steps=7,
    start_time_s=0.0,
    end_time_s=24.5,
    step_outcomes=[...],   # List[StepOutcome]
    robot_traces=[...],    # List[RobotTrace]
)

# Process AAS — pre-fabrication BoP (OPC 40570 Cut/Strip/Crimp)
prefab_bundle = build_aas_from_prefab(harness)

# Process AAS — production order
order_bundle = build_aas_from_order(
    order_number="PO-2026-001",
    production_quantity=10,
    target_delivery_date="2026-12-31",
    harness_variant_asset_ids=["urn:NEXUS:harness:WH-SIMPLE-001:wh-001"],
    bop_asset_id="urn:NEXUS:bop:example_production_001",
    station_asset_id="urn:NEXUS:station:station_01",
)

# Serialize all to JSON
write_aas_json("output/wire_harness.json", cdm_result.wire_harness_bundle)
write_aas_json("output/components.json", *cdm_result.component_bundles)
write_aas_json("output/station.json", station_bundle)
write_aas_json("output/bop.json", bop_bundle)
write_aas_json("output/layout.json", layout_bundle)
write_aas_json("output/delivery.json", delivery_bundle)
write_aas_json("output/workspace.json", workspace_bundle)
write_aas_json("output/trace.json", trace_bundle)
write_aas_json("output/prefab.json", prefab_bundle)
write_aas_json("output/order.json", order_bundle)
```