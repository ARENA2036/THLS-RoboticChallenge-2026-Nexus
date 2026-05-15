"""
Configuration and default parameters for the Layout Generator.
"""

from dataclasses import dataclass


@dataclass
class LayoutConfig:
    """Configuration container for layout generation parameters."""

    # Peg placement parameters
    default_peg_interval_mm: float = 250.0
    intersection_offset_mm: float = 0.0

    # Connector holder parameters
    connector_inward_offset_mm: float = 30.0  # Offset toward center for cable slack
    connector_buffer_zone_mm: float = 50.0    # Clearance zone around connectors

    # Optimization parameters
    merge_distance_mm: float = 80.0

    # Holder type thresholds (based on max dimension)
    holder_small_threshold_mm: float = 30.0
    holder_medium_threshold_mm: float = 60.0

    # Default connector dimensions (when not specified)
    default_connector_width_mm: float = 30.0
    default_connector_height_mm: float = 20.0
    default_connector_depth_mm: float = 15.0


# Singleton default parameters
DEFAULT_PARAMETERS = LayoutConfig()


@dataclass
class BoardDefaults:
    """Default board configuration values."""

    width_mm: float = 1200.0
    height_mm: float = 800.0
    offset_x: float = 0.0
    offset_y: float = 0.0


BOARD_DEFAULTS = BoardDefaults()
