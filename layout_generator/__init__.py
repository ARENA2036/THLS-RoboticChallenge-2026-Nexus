"""
Layout Generator Module

Generates peg and connector holder positions for wire harness assembly boards
based on the Wire Harness CDM (Canonical Description Model).
"""

__version__ = "0.1.0"
__author__ = "Wire Harness Team"

from .LayoutConfig import DEFAULT_PARAMETERS, LayoutConfig
from .LayoutModels import (
    BoardConfig,
    ConnectorHolderPosition,
    HolderType,
    LayoutParameters,
    LayoutResponse,
    PegPlacementReason,
    PegPosition,
)

__all__ = [
    "LayoutConfig",
    "DEFAULT_PARAMETERS",
    "BoardConfig",
    "LayoutParameters",
    "LayoutResponse",
    "ConnectorHolderPosition",
    "PegPosition",
    "HolderType",
    "PegPlacementReason",
]
