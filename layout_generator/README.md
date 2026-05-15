The **Layout Generator** module implements **Step 2: Resource Modeling** of the robotic assembly pipeline. It automatically derives the spatial layout of the assembly board and robotic workcell from the [Canonical Description Model (CDM)](../cdm), establishing the **Resource (R)** dimension of the Product-Process-Resource (PPR) model.

By transforming product topology into a physical board configuration (pegs and connector holders), this module eliminates the manual engineering effort traditionally required to design variant-specific assembly boards.

## Features

- **Connector Holder Placement**: Positions connectors with mating direction vectors and buffer zones
- **Peg Placement**: Automated cable support peg positioning with rules for:
  - Breakout points (branch nodes with degree > 1)
  - Regular interval placement along segments
- **Peg Orientation**: Pegs are oriented perpendicular to the cable direction
- **Layout Optimization**: Merges nearby pegs and avoids forbidden zones
- **Visualization**: Matplotlib-based board layout rendering with PNG/SVG export

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# For development/testing
pip install -r requirements-test.txt
```

## Usage

### Python API

```python
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import LayoutRequest, BoardConfig, LayoutParameters, WireHarness

# Create service
service = LayoutGeneratorService()

# Build request
request = LayoutRequest(
    harness=your_wire_harness,  # WireHarness CDM
    board_config=BoardConfig(width_mm=1200, height_mm=800),
    parameters=LayoutParameters(),  # Uses defaults
)

# Generate layout
response = service.generate_layout(request)

# Access results
print(f"Connector holders: {len(response.connector_holders)}")
print(f"Pegs: {len(response.pegs)}")
print(f"Metrics: {response.metrics}")
```

### Visualization

```python
from layout_generator.visualizer.BoardLayoutVisualizer import BoardLayoutVisualizer

visualizer = BoardLayoutVisualizer(board_config)
visualizer.add_harness(harness)
visualizer.add_layout(response)

# Render and display
visualizer.render()
visualizer.show()

# Or export
visualizer.export_png("board_layout.png")
visualizer.export_svg("board_layout.svg")
```

## Configuration Parameters

### LayoutConfig (LayoutConfig.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `default_peg_interval_mm` | 250.0 | Standard spacing between interval pegs along segments |
| `connector_inward_offset_mm` | 30.0 | Offset toward board center for cable slack at connectors |
| `connector_buffer_zone_mm` | 50.0 | Clearance radius around connectors where no pegs are placed |
| `merge_distance_mm` | 80.0 | Maximum distance for merging nearby pegs into one |
| `holder_small_threshold_mm` | 30.0 | Max dimension threshold for SMALL holder type |
| `holder_medium_threshold_mm` | 60.0 | Max dimension threshold for MEDIUM holder type (>60 = LARGE) |
| `default_connector_width_mm` | 30.0 | Default connector width when not specified in CDM |
| `default_connector_height_mm` | 20.0 | Default connector height when not specified in CDM |
| `default_connector_depth_mm` | 15.0 | Default connector depth when not specified in CDM |

### BoardDefaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `width_mm` | 1200.0 | Default board width |
| `height_mm` | 800.0 | Default board height |
| `offset_x` | 0.0 | X offset for coordinate transformation |
| `offset_y` | 0.0 | Y offset for coordinate transformation |

## Algorithms

### Connector Placement (ConnectorPlacementEngine)

The connector placement algorithm positions connector holders on the board:

1. **Position Calculation**: 
   - Reads connector position from the associated node in the harness topology
   - Applies `connector_inward_offset_mm` to shift the holder toward the board center (provides cable slack)

2. **Mating Direction**:
   - If explicitly specified in `ConnectorOccurrence.mating_direction`, uses that vector
   - Otherwise, computes direction based on connected segment geometry (points away from the cable)

3. **Holder Type Classification**:
   - Based on max(width, height, depth) of connector dimensions
   - `SMALL`: max dimension < 30mm
   - `MEDIUM`: max dimension 30-60mm  
   - `LARGE`: max dimension > 60mm

4. **Buffer Zone**:
   - Each holder has a circular buffer zone (`connector_buffer_zone_mm`)
   - Pegs within this zone are removed during optimization

### Peg Placement (PegPlacementEngine)

The peg placement algorithm determines support peg positions along cable segments:

1. **Breakout Pegs** (at branch points):
   - Placed at nodes with degree > 1 (where multiple segments meet)
   - Provides support at cable junctions
   - Orientation: perpendicular to one of the connected segments

2. **Interval Pegs** (regular spacing):
   - Placed along segments at regular intervals (`default_peg_interval_mm`)
   - Number of pegs = floor(segment_length / interval)
   - Evenly distributed along the segment
   - Orientation: perpendicular to segment direction

3. **Peg Orientation**:
   - All pegs are oriented perpendicular to the cable direction (segment angle + 90°)
   - Visualized as thin rectangles spanning across the cable path

### Layout Optimization (LayoutOptimizer)

The optimizer refines the initial peg placement:

1. **Peg Merging**:
   - Pegs within `merge_distance_mm` are merged into a single peg at the centroid
   - Priority: BREAKOUT_POINT > INTERVAL (higher priority reason is preserved)
   - Orientation from the highest-priority peg is used

2. **Buffer Zone Filtering**:
   - Pegs inside connector buffer zones are removed

3. **Forbidden Zone Handling**:
   - Pegs in forbidden zones (worker areas, custom exclusions) are shifted to nearest valid position
   - If no valid position found, peg is kept at original location

## Project Structure

```
layout_generator/
├── __init__.py
├── LayoutConfig.py              # Default parameters
├── LayoutModels.py              # Pydantic models
├── LayoutGeneratorService.py    # Main service orchestration
├── algorithms/
│   ├── ConnectorPlacementEngine.py
│   ├── PegPlacementEngine.py
│   └── LayoutOptimizer.py
├── visualizer/
│   ├── BoardLayoutVisualizer.py
│   └── VisualizerStyle.py
├── examples/
│   └── sample_usage.py
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── edge_cases/
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=. --cov-report=html

# Specific test categories
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/edge_cases/ -v
```

## License

Internal use only.

---
> [!NOTE]
> The generated layout is serialized as **BoardLayoutAAS** and **WorkspaceZonesAAS** submodels, enabling real-time updates and synchronization with the robotic workcell. See Section IV-B of the [ETFA 2026 Paper](../ETFA_2026__From_Design_to_Action__Enabling_End_to_End_Robotic_Wire_Harness_Assembly.pdf) for algorithmic details.
