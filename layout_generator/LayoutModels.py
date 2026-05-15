"""
Pydantic models for the Layout Generator.
Imports CDM types from public schema and defines layout-specific extensions.
"""

import math
import sys
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

# Add parent directory to path for CDM imports
_parent_dir = Path(__file__).resolve().parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

# Import CDM types from the canonical schema
from public.cdm.definitions.cdm_schema import (
    Accessory,
    AccessoryOccurrence,
    BezierCurve,
    # Geometry
    CartesianPoint,
    Cavity,
    Connection,
    Connector,
    ContactPoint,
    Core,
    CoreOccurrence,
    # Connections & Routing
    Extremity,
    Fixing,
    FixingOccurrence,
    Node,
    # Harness structure
    ProtectionArea,
    Routing,
    Segment,
    Slot,
    SpecialWireOccurrence,
    Terminal,
    Wire,
    # Wire definitions
    WireColor,
    # Root
    WireHarness,
    WireLength,
    WireOccurrence,
    # Component definitions
    WireProtection,
    # Occurrences
    WireProtectionOccurrence,
)
from public.cdm.definitions.cdm_schema import (
    ConnectorOccurrence as CDMConnectorOccurrence,
)

from .LayoutConfig import BOARD_DEFAULTS, DEFAULT_PARAMETERS

# Re-export CDM types for convenience
__all__ = [
    # CDM types (re-exported)
    "CartesianPoint", "BezierCurve", "WireProtection", "Accessory", "Fixing",
    "Cavity", "Slot", "Connector", "Terminal", "WireColor", "Core", "Wire",
    "WireLength", "WireProtectionOccurrence", "AccessoryOccurrence",
    "FixingOccurrence", "ContactPoint", "CoreOccurrence", "WireOccurrence",
    "SpecialWireOccurrence", "ProtectionArea", "Node", "Extremity",
    "Connection", "Routing", "Segment", "WireHarness",
    # Layout extensions
    "ConnectorOccurrence",
    # Layout-specific types
    "HolderType", "PegPlacementReason", "Point2D", "Vector2D",
    "ForbiddenZone", "BoardConfig", "LayoutParameters", "LayoutRequest",
    "ConnectorHolderPosition", "PegPosition", "LayoutMetrics",
    "LayoutResponse",
]


# ============================================================================
# Layout Generator Enums
# ============================================================================

class HolderType(StrEnum):
    """Connector holder size classification."""
    UNSPECIFIED = "UNSPECIFIED"
    SMALL = "SMALL"           # < 30mm
    MEDIUM = "MEDIUM"         # 30-60mm
    LARGE = "LARGE"           # > 60mm


class PegPlacementReason(StrEnum):
    """Reason for peg placement at a specific location."""
    UNSPECIFIED = "UNSPECIFIED"
    BREAKOUT_POINT = "BREAKOUT_POINT"       # At node with degree > 1
    INTERVAL = "INTERVAL"                    # Regular interval placement




# ============================================================================
# Layout Output Types (2D board coordinates)
# ============================================================================

class Point2D(BaseModel):
    """2D point in board coordinates (mm)."""
    x: float
    y: float


class Vector2D(BaseModel):
    """2D vector for directions."""
    x: float
    y: float

    def normalize(self) -> "Vector2D":
        """Return normalized unit vector."""
        magnitude = math.sqrt(self.x ** 2 + self.y ** 2)
        if magnitude == 0:
            return Vector2D(x=1.0, y=0.0)
        return Vector2D(x=self.x / magnitude, y=self.y / magnitude)

    def to_angle_deg(self) -> float:
        """Convert to angle in degrees (0 = right, 90 = up)."""
        return math.degrees(math.atan2(self.y, self.x))


# ============================================================================
# Layout Extensions of CDM Types
# ============================================================================

class ConnectorOccurrence(CDMConnectorOccurrence):
    """
    Extended ConnectorOccurrence with layout-specific fields.
    Inherits all CDM fields and adds layout generation requirements.
    """
    # Layout generation fields
    node_id: str | None = None  # Associated topology node
    mating_direction: Vector2D | None = None
    physical_width: float = Field(default=DEFAULT_PARAMETERS.default_connector_width_mm)
    physical_height: float = Field(default=DEFAULT_PARAMETERS.default_connector_height_mm)
    physical_depth: float = Field(default=DEFAULT_PARAMETERS.default_connector_depth_mm)


# ============================================================================
# Board Configuration
# ============================================================================

class ForbiddenZone(BaseModel):
    """Area where pegs/holders cannot be placed."""
    id: str
    vertices: list[Point2D] = Field(default_factory=list)


class BoardConfig(BaseModel):
    """Assembly board configuration."""
    width_mm: float = Field(default=BOARD_DEFAULTS.width_mm)
    height_mm: float = Field(default=BOARD_DEFAULTS.height_mm)
    forbidden_zones: list[ForbiddenZone] = Field(default_factory=list)
    offset_x: float = Field(default=BOARD_DEFAULTS.offset_x)
    offset_y: float = Field(default=BOARD_DEFAULTS.offset_y)


class LayoutParameters(BaseModel):
    """Parameters controlling layout generation."""
    # Peg placement
    default_peg_interval_mm: float = Field(default=DEFAULT_PARAMETERS.default_peg_interval_mm)
    intersection_offset_mm: float = Field(default=DEFAULT_PARAMETERS.intersection_offset_mm, ge=0.0)

    # Connector holder
    connector_inward_offset_mm: float = Field(default=DEFAULT_PARAMETERS.connector_inward_offset_mm)
    connector_buffer_zone_mm: float = Field(default=DEFAULT_PARAMETERS.connector_buffer_zone_mm)

    # Optimization
    merge_distance_mm: float = Field(default=DEFAULT_PARAMETERS.merge_distance_mm)


# ============================================================================
# Layout Request
# ============================================================================

class LayoutRequest(BaseModel):
    """Request for layout generation."""
    harness: WireHarness
    board_config: BoardConfig = Field(default_factory=BoardConfig)
    parameters: LayoutParameters = Field(default_factory=LayoutParameters)


# ============================================================================
# Layout Response
# ============================================================================

class ConnectorHolderPosition(BaseModel):
    """Generated connector holder position."""
    connector_id: str
    position: Point2D
    orientation_deg: float  # Mating direction angle
    holder_type: HolderType
    buffer_radius_mm: float
    width_mm: float
    height_mm: float


class PegPosition(BaseModel):
    """Generated peg position."""
    id: str
    position: Point2D
    segment_id: str
    reason: PegPlacementReason
    orientation_deg: float = 0.0  # Perpendicular to cable direction
    merged_from: str | None = None


class LayoutMetrics(BaseModel):
    """Statistics about the generated layout."""
    total_pegs: int = 0
    total_holders: int = 0
    merged_positions: int = 0
    shifted_positions: int = 0
    board_utilization_percent: float = 0.0

    # Breakdown by reason
    breakout_pegs: int = 0
    interval_pegs: int = 0
    intersection_offset_applied_count: int = 0
    intersection_offset_fallback_count: int = 0
    intersection_offset_clamped_count: int = 0


class LayoutResponse(BaseModel):
    """Response from layout generation."""
    connector_holders: list[ConnectorHolderPosition] = Field(default_factory=list)
    pegs: list[PegPosition] = Field(default_factory=list)
    metrics: LayoutMetrics = Field(default_factory=LayoutMetrics)
