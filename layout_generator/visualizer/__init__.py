"""
Board Layout Visualizer.

Provides comprehensive 2D visualization of wire harness board layouts including:
- Individual wire paths
- Connector positions with cavities
- Peg positions (color-coded by placement reason)
- Forbidden zones

Quick usage:
    >>> from layout_generator.visualizer import plot_harness
    >>> plot_harness(my_harness)
"""

from .BoardLayoutVisualizer import BoardLayoutVisualizer, plot_harness
from .VisualizerStyle import VisualizerStyle

__all__ = [
    "BoardLayoutVisualizer",
    "VisualizerStyle",
    "plot_harness",
]
