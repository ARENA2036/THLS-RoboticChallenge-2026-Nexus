"""
Canonical Data Model for Wire Harnesses.
Source of truth for the CDM definition.
"""

from typing import List, Optional, Literal, Union
from pydantic import BaseModel


# === Geometry ===
class CartesianPoint(BaseModel):
    id: Optional[str] = None
    coord_x: float
    coord_y: float
    coord_z: float = 0.0


class BezierCurve(BaseModel):
    id: Optional[str] = None
    degree: int
    control_points: List[CartesianPoint]


# === Component Definitions ===

class WireProtection(BaseModel):
    """Definition of wire protection material (tape, tube, conduit, etc.)."""
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    protection_type: Optional[Literal["tape", "tube", "conduit", "sleeve", "grommet"]] = None
    material: Optional[str] = None
    mass_g: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None


class Accessory(BaseModel):
    """Definition of an accessory component (e.g., hybrid housing assemblies)."""
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    accessory_type: Optional[str] = None  # e.g., "ZUB"
    material: Optional[str] = None
    mass_g: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None


class Fixing(BaseModel):
    """Definition of a fixing component (cable ties, clips, etc.)."""
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    fixing_type: Optional[str] = None  # cable tie, clip, etc.
    material: Optional[str] = None
    mass_g: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None


class Cavity(BaseModel):
    id: str
    cavity_number: str
    is_available: bool = True
    has_integrated_terminal: bool = False


class Slot(BaseModel):
    id: str
    slot_number: str
    num_cavities: int
    cavities: List[Cavity] = []
    gender: Literal["male", "female", "na"] = "na"


class Connector(BaseModel):
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    connector_type: Literal["housing", "module", "inline", "splice", "terminal_block"]
    housing_color: Optional[str] = None
    housing_code: Optional[str] = None  # e.g., "A", "B" for coding
    material: Optional[str] = None
    mass_g: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None
    slots: List[Slot] = []


class Terminal(BaseModel):
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    terminal_type: Literal["pin", "socket", "ring", "spade", "blade", "splice"]
    gender: Literal["male", "female", "na"] = "na"
    min_cross_section_mm: Optional[float] = None
    max_cross_section_mm: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None


# === Wires and Cores Definitions ===

class WireColor(BaseModel):
    color_type: str  # e.g., "Base Color", "Identification Color 1"
    color_code: str  # e.g., "RD", "BU", "YE"


class Core(BaseModel):
    """Individual core within a multi-core cable definition."""
    id: str
    label: Optional[str] = None
    wire_type: Optional[str] = None
    cross_section_area_mm2: Optional[float] = None
    outside_diameter_mm: Optional[float] = None
    colors: List[WireColor] = []
    cable_designator: Optional[str] = None  # e.g., "FLRYA 0.35 GN/BR"


class Wire(BaseModel):
    id: str
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    wire_type: Literal["wire", "cable", "twisted_pair", "coaxial", "shielded", "multi_core"]
    cross_section_area_mm2: Optional[float] = None
    outside_diameter: Optional[float] = None
    material_conductor: Optional[str] = None
    material_insulation: Optional[str] = None
    mass_g: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    digikey_url: Optional[str] = None
    cover_colors: List[WireColor] = []
    cores: List[Core] = []  # For multi-core cables


class WireLength(BaseModel):
    """Length specification with type descriptor."""
    length_type: str  # e.g., "dmu length", "nominal", "production"
    length_mm: float


# === Occurrences ===

class WireProtectionOccurrence(BaseModel):
    """Instance of wire protection used in the harness."""
    id: str
    protection: WireProtection  # Reference to WireProtection
    label: Optional[str] = None


class AccessoryOccurrence(BaseModel):
    """Instance of an accessory used in the harness."""
    id: str
    accessory: Accessory  # Reference to Accessory
    label: Optional[str] = None
    position: Optional[CartesianPoint] = None
    referenced_connectors: List[Connector] = []


class FixingOccurrence(BaseModel):
    """Instance of a fixing used in the harness."""
    id: str
    fixing: Fixing
    label: Optional[str] = None
    position: Optional[CartesianPoint] = None


class ContactPoint(BaseModel):
    id: str
    terminal: Terminal
    cavity: Cavity


class ConnectorOccurrence(BaseModel):
    id: str
    connector: Connector
    label: Optional[str] = None
    description: Optional[str] = None
    position: Optional[CartesianPoint] = None
    slots: List[Slot] = []
    contact_points: List[ContactPoint] = []


class CoreOccurrence(BaseModel):
    """Instance of a core within a special wire occurrence."""
    id: str
    core: Core
    wire_number: Optional[str] = None  # e.g., "UTP_1", "Shielding"
    length: Optional[WireLength] = None


class WireOccurrence(BaseModel):
    """Instance of a simple wire."""
    id: str
    wire: Wire
    wire_number: Optional[str] = None
    length: Optional[WireLength] = None
    length_dmu: Optional[float] = None
    length_production: Optional[float] = None
    printed_label: Optional[str] = None


class SpecialWireOccurrence(BaseModel):
    """Instance of a multi-core/coaxial/shielded cable with nested core occurrences."""
    id: str
    wire: Wire
    special_wire_id: Optional[str] = None
    length: Optional[WireLength] = None
    core_occurrences: List[CoreOccurrence] = []


# === Harness Structure ===

class ProtectionArea(BaseModel):
    """Defines where wire protection is applied on a segment."""
    id: Optional[str] = None
    start_location: float  # 0.0 to 1.0, position along segment
    end_location: float  # 0.0 to 1.0, position along segment
    wire_protection_occurrence: WireProtectionOccurrence


class Node(BaseModel):
    id: str
    label: Optional[str] = None
    position: CartesianPoint


class Segment(BaseModel):
    id: str
    label: Optional[str] = None
    start_node: Node
    end_node: Node
    length: Optional[float] = None
    virtual_length: Optional[float] = None
    physical_length: Optional[float] = None
    center_curve: Optional[BezierCurve] = None
    protection_areas: List[ProtectionArea] = []
    min_bend_radius_mm: Optional[float] = None
    fixings: List[FixingOccurrence] = []


# === Connections & Routing ===

class Extremity(BaseModel):
    id: Optional[str] = None
    position_on_wire: float  # 0.0 = start, 1.0 = end
    contact_point: ContactPoint


class Connection(BaseModel):
    id: str
    signal_name: Optional[str] = None
    wire_occurrence: Union[WireOccurrence, CoreOccurrence] # One core of special wire forms connection
    extremities: List[Extremity] = []
    segments: List[Segment] = []


class Routing(BaseModel):
    id: Optional[str] = None
    routed_connection: Connection
    segments: List[Segment]


# === Wire Harness ===

class WireHarness(BaseModel):
    id: str
    part_number: str
    version: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None
    created_at: str
    modified_at: Optional[str] = None

    # Part definitions
    connectors: List[Connector] = []
    terminals: List[Terminal] = []
    wires: List[Wire] = []
    wire_protections: List[WireProtection] = []
    accessories: List[Accessory] = []
    fixings: List[Fixing] = []

    # Occurrences
    connector_occurrences: List[ConnectorOccurrence] = []
    wire_occurrences: List[WireOccurrence] = []
    special_wire_occurrences: List[SpecialWireOccurrence] = []
    wire_protection_occurrences: List[WireProtectionOccurrence] = []
    accessory_occurrences: List[AccessoryOccurrence] = []
    fixing_occurrences: List[FixingOccurrence] = []

    connections: List[Connection] = []

    nodes: List[Node] = []
    segments: List[Segment] = []
    routings: List[Routing] = []
