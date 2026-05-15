#!/usr/bin/env python3
"""
Generate publication-quality vector figure of the medium harness board layout.

Output: 698f3ae54d2ddb0627e27162/figures/medium_layout.pdf

Run from project root:
    python layout_generator/examples/generate_paper_figure.py
"""

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from public.cdm.examples import load_example
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import BoardConfig, LayoutParameters, LayoutRequest
from layout_generator.visualizer import BoardLayoutVisualizer

# ── paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures" / "medium_layout.pdf"

# ── load harness ───────────────────────────────────────────────────────────
harness = load_example("medium")

# ── generate layout ────────────────────────────────────────────────────────
# Board config: derive from harness node extents with generous margin
all_x = [node.position.coord_x for node in harness.nodes]
all_y = [node.position.coord_y for node in harness.nodes]
margin = 80  # mm
board_config = BoardConfig(
    width_mm=max(all_x) - min(all_x) + 2 * margin,
    height_mm=max(all_y) - min(all_y) + 2 * margin,
    offset_x=-min(all_x) + margin,
    offset_y=-min(all_y) + margin,
)

service = LayoutGeneratorService()
request = LayoutRequest(
    harness=harness,
    board_config=board_config,
    parameters=LayoutParameters(),
)
layout_response = service.generate_layout(request)

# ── render ─────────────────────────────────────────────────────────────────
# IEEE single-column figure: ~3.5 inches wide
# Derive height from board aspect ratio
aspect = board_config.width_mm / board_config.height_mm
fig_width = 3.5  # inches (single-column IEEE)
fig_height = fig_width / aspect

# Global font settings for publication
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 7,
    "axes.titlesize": 0,      # hide title
    "axes.labelsize": 7,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "axes.linewidth": 0.6,
    "lines.linewidth": 0.8,
})

visualizer = BoardLayoutVisualizer(board_config)
visualizer.add_harness(harness)
visualizer.add_layout(layout_response)

fig = visualizer.render(
    show_grid=True,
    show_forbidden_zones=False,
    show_labels=True,
    show_buffer_zones=False,
    show_individual_wires=True,
    show_legend=False,
    figsize=(fig_width, fig_height),
)

# Clean up axes: remove title, keep axis labels for spatial reference
ax = fig.axes[0]
ax.set_title("")
ax.set_xlabel("x (mm)")
ax.set_ylabel("y (mm)")

# Tight layout with minimal padding
fig.tight_layout(pad=0.3)

# ── export ─────────────────────────────────────────────────────────────────
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
visualizer.export_pdf(str(OUTPUT_PATH))
print(f"Saved: {OUTPUT_PATH}")
