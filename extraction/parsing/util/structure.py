#!/usr/bin/env python3
"""Standalone wiring diagram extraction pipeline using Docling VLM.

Usage:
    python docling_vlm.py --pdf <path_to_pdf.pdf>
    python docling_vlm.py --pdf diagram.pdf --output extracted.json
"""

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Any, Dict
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)

# =============================================================================
# Enumerations
# =============================================================================

class WireColor(str, Enum):
    """Standard wire colors found in the diagram."""
    GREEN = "green"
    BLUE = "blue"
    RED = "red"
    ORANGE = "orange"
    BLACK = "black"
    WHITE = "white"
    YELLOW = "yellow"
    BROWN = "brown"
    GRAY = "gray"
    UNKNOWN = "unknown"


class ConnectorType(str, Enum):
    """Types of connectors based on the diagram."""
    MODULE_CONNECTOR = "module_connector"
    SIGNAL_CONNECTOR = "signal_connector"
    POWER_CONNECTOR = "power_connector"


# =============================================================================
# Core Models
# =============================================================================

class ConnectorPin(BaseModel):
    """Represents a single pin within a connector."""
    pin_number: int = Field(..., ge=1, description="Physical pin number (1-indexed)")
    pin_label: Optional[str] = Field(None, description="Pin label (e.g., 'P1', 'P2')")
    signal_name: Optional[str] = Field(None, description="Signal name/function of the pin")


class Connector(BaseModel):
    """Represents a physical connector in the harness."""
    connector_id: str = Field(..., description="Unique connector identifier (e.g., ST_1)")
    connector_name: str = Field(..., description="Human-readable name")
    connector_type: ConnectorType = Field(..., description="Type of connector")
    pin_count: int = Field(..., ge=1, description="Total number of pins")
    description: Optional[str] = Field(None, description="Additional description")
    pins: List[ConnectorPin] = Field(default_factory=list, description="List of pins in this connector")


class Wire(BaseModel):
    """Represents a single wire connection between two pins."""
    wire_id: str = Field(..., description="Unique wire identifier (BOM part_name)")
    part_number: Optional[str] = Field(None, description="BOM part_number (e.g. FLRY-0.35-RD)")
    source_connector_id: str = Field(..., description="ID of the source connector")
    source_pin_number: int = Field(..., ge=1, description="Pin number in source connector")
    destination_connector_id: str = Field(..., description="ID of the destination connector")
    destination_pin_number: int = Field(..., ge=1, description="Pin number in destination connector")
    color: WireColor = Field(..., description="Color of the wire")
    gauge: Optional[float] = Field(None, description="Wire gauge in AWG")
    notes: Optional[str] = Field(None, description="Additional notes about this wire")


class WireGroup(BaseModel):
    """Represents a group of wires with the same color and purpose."""
    group_id: str = Field(..., description="Unique group identifier")
    group_name: str = Field(..., description="Name of the wire group")
    color: WireColor = Field(..., description="Color of wires in this group")
    wires: List[Wire] = Field(..., description="Wires belonging to this group")
    notes: Optional[str] = Field(None, description="Description of the wire group purpose")


class WiringDiagram(BaseModel):
    """Complete representation of a wiring diagram/scheme."""
    diagram_id: str = Field(..., description="Unique identifier for this diagram")
    diagram_name: str = Field(..., description="Name of the wiring diagram")
    description: Optional[str] = Field(None, description="Overall description of the diagram")
    version: str = Field(default="1.0", description="Version of this diagram")
    created_at: Optional[datetime] = Field(default_factory=datetime.now, description="Creation timestamp")
    author: Optional[str] = Field(None, description="Author/creator of the diagram")
    project_name: Optional[str] = Field(None, description="Associated project name")
    connectors: List[Connector] = Field(default_factory=list, description="All connectors in the diagram")
    wires: List[Wire] = Field(default_factory=list, description="All wire connections")
    wire_groups: List[WireGroup] = Field(default_factory=list, description="Grouped wires by color/purpose")
    notes: Optional[str] = Field(None, description="General notes about the diagram")