"""
Visual style definitions for the board layout visualizer.
"""

from dataclasses import dataclass


@dataclass
class VisualizerStyle:
    """Visual style configuration for the board layout visualizer."""

    # Board
    board_background_color: str = "#FFFFFF"
    board_border_color: str = "#333333"
    board_border_width: float = 2.0

    # Grid
    grid_color: str = "#E5E5E5"
    grid_line_width: float = 0.5
    grid_spacing_mm: float = 50.0

    # Forbidden zones
    forbidden_zone_color: str = "#EF4444"
    forbidden_zone_alpha: float = 0.2
    forbidden_zone_edge_color: str = "#DC2626"
    forbidden_zone_edge_width: float = 1.0

    # Cable segments
    segment_color: str = "#171717"
    segment_line_width: float = 2.0

    # Nodes
    node_color: str = "#EF4444"
    node_marker: str = "D"  # Diamond
    node_size: float = 80.0

    # Connector holders
    connector_color: str = "#3B82F6"
    connector_edge_color: str = "#1D4ED8"
    connector_edge_width: float = 2.0
    connector_alpha: float = 0.8

    # Buffer zones
    buffer_zone_color: str = "#93C5FD"
    buffer_zone_alpha: float = 0.3
    buffer_zone_line_style: str = "--"
    buffer_zone_line_width: float = 1.0

    # Mating direction arrows
    arrow_color: str = "#1D4ED8"
    arrow_width: float = 2.0
    arrow_head_width: float = 8.0
    arrow_head_length: float = 6.0

    # Pegs by reason
    peg_colors: dict = None
    peg_width_mm: float = 8.0    # Width of peg rectangle (thin dimension)
    peg_length_mm: float = 30.0  # Length of peg rectangle (perpendicular to cable)

    def __post_init__(self):
        if self.peg_colors is None:
            self.peg_colors = {
                "BREAKOUT_POINT": "#22C55E",      # Green
                "INTERVAL": "#6B7280",             # Gray
                "UNSPECIFIED": "#9CA3AF",          # Light gray
            }

    # Labels
    label_font_size: int = 8
    label_color: str = "#374151"
    connector_label_font_size: int = 9
    connector_label_color: str = "#1F2937"

    # Figure
    figure_dpi: int = 150
    figure_padding: float = 0.1  # 10% padding around content


# Default style instance
DEFAULT_STYLE = VisualizerStyle()
