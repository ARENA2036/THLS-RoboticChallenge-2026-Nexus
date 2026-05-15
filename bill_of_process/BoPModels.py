"""
Pydantic models for the Bill of Process (BoP).

Defines process types, typed parameter models, process steps, assembly phases,
and the top-level ProductionBillOfProcess.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Discriminator, Field, Tag, model_validator


# ============================================================================
# Enums
# ============================================================================

class PhaseType(StrEnum):
    """Assembly phase classification."""
    PREPARATION = "PREPARATION"
    BOARD_SETUP = "BOARD_SETUP"
    WIRE_ROUTING = "WIRE_ROUTING"
    PROTECTION_AND_FIXING = "PROTECTION_AND_FIXING"
    CONNECTOR_ASSEMBLY = "CONNECTOR_ASSEMBLY"
    FINALIZATION = "FINALIZATION"


class ProcessType(StrEnum):
    """Catalog of available high-level process types.

    Each value maps to a specific parameter model.
    Extend this enum (and the ProcessParameters union) to add new process types.
    """
    # Board setup
    PLACE_PEG = "PLACE_PEG"
    PLACE_CONNECTOR_HOLDER = "PLACE_CONNECTOR_HOLDER"
    # Wire routing
    ROUTE_WIRE = "ROUTE_WIRE"
    # Protection and fixing
    APPLY_WIRE_PROTECTION = "APPLY_WIRE_PROTECTION"
    APPLY_FIXING = "APPLY_FIXING"
    # Finalization
    REMOVE_HARNESS = "REMOVE_HARNESS"


# ============================================================================
# Process Parameters -- one model per ProcessType
# ============================================================================

class PlacePegParameters(BaseModel):
    """Parameters for PLACE_PEG process."""
    parameter_type: Literal["PLACE_PEG"] = "PLACE_PEG"
    peg_id: str
    position_x_mm: float
    position_y_mm: float
    orientation_deg: float
    segment_id: str
    placement_reason: str


class PlaceConnectorHolderParameters(BaseModel):
    """Parameters for PLACE_CONNECTOR_HOLDER process."""
    parameter_type: Literal["PLACE_CONNECTOR_HOLDER"] = "PLACE_CONNECTOR_HOLDER"
    connector_occurrence_id: str
    position_x_mm: float
    position_y_mm: float
    orientation_deg: float
    holder_type: str
    width_mm: float
    height_mm: float
    buffer_radius_mm: float


class RouteWireExtremity(BaseModel):
    """One end of a wire being routed -- identifies the target cavity."""
    connector_occurrence_id: str
    contact_point_id: str
    cavity_id: str
    cavity_number: str
    terminal_type: str


class RouteWireParameters(BaseModel):
    """Parameters for ROUTE_WIRE process.

    Pull test is implicit in this step -- the robotic station
    performs it as part of the internal action sequence.
    """
    parameter_type: Literal["ROUTE_WIRE"] = "ROUTE_WIRE"
    connection_id: str
    wire_occurrence_id: str
    wire_part_number: str
    ordered_segment_ids: List[str]
    ordered_peg_ids: List[str]
    extremities: List[RouteWireExtremity]


class ApplyWireProtectionParameters(BaseModel):
    """Parameters for APPLY_WIRE_PROTECTION process.

    Applied per bundle after all wires in the segment are routed.
    """
    parameter_type: Literal["APPLY_WIRE_PROTECTION"] = "APPLY_WIRE_PROTECTION"
    wire_protection_occurrence_id: str
    segment_id: str
    start_location: float  # 0.0 to 1.0
    end_location: float  # 0.0 to 1.0
    protection_type: str
    part_number: str


class ApplyFixingParameters(BaseModel):
    """Parameters for APPLY_FIXING process."""
    parameter_type: Literal["APPLY_FIXING"] = "APPLY_FIXING"
    fixing_occurrence_id: str
    segment_id: Optional[str] = None
    position_on_segment: Optional[float] = None  # 0.0 to 1.0
    fixing_type: str
    part_number: str


class RemoveHarnessParameters(BaseModel):
    """Parameters for REMOVE_HARNESS process."""
    parameter_type: Literal["REMOVE_HARNESS"] = "REMOVE_HARNESS"
    harness_id: str


# ============================================================================
# Discriminated Union of all parameter types
# ============================================================================

def _get_parameter_discriminator_value(value: object) -> str:
    """Extract the discriminator value from a parameter instance or dict."""
    if isinstance(value, dict):
        return value.get("parameter_type", "")
    return getattr(value, "parameter_type", "")


ProcessParameters = Annotated[
    Union[
        Annotated[PlacePegParameters, Tag("PLACE_PEG")],
        Annotated[PlaceConnectorHolderParameters, Tag("PLACE_CONNECTOR_HOLDER")],
        Annotated[RouteWireParameters, Tag("ROUTE_WIRE")],
        Annotated[ApplyWireProtectionParameters, Tag("APPLY_WIRE_PROTECTION")],
        Annotated[ApplyFixingParameters, Tag("APPLY_FIXING")],
        Annotated[RemoveHarnessParameters, Tag("REMOVE_HARNESS")],
    ],
    Discriminator(_get_parameter_discriminator_value),
]


# ============================================================================
# Process Step and Assembly Phase
# ============================================================================

class ProcessStep(BaseModel):
    """A single high-level process step in the Bill of Process.

    Each step is a self-contained command dispatched to a station.
    The station decomposes it into internal sub-actions.
    """
    step_id: str
    sequence_number: int
    process_type: ProcessType
    harness_id: str
    station_id: str
    description: str
    parameters: ProcessParameters
    depends_on: List[str] = Field(default_factory=list)
    estimated_duration_s: Optional[float] = None

    @model_validator(mode="after")
    def validate_process_type_matches_parameters(self) -> "ProcessStep":
        """Ensure process_type and parameter_type are always aligned."""
        parameter_type = self.parameters.parameter_type
        if self.process_type.value != parameter_type:
            raise ValueError(
                "process_type and parameters.parameter_type mismatch: "
                f"{self.process_type.value} != {parameter_type}"
            )
        return self


class AssemblyPhase(BaseModel):
    """A phase in the assembly process, containing ordered steps."""
    phase_type: PhaseType
    phase_label: str
    steps: List[ProcessStep] = Field(default_factory=list)


# ============================================================================
# Top-level BoP
# ============================================================================

class HarnessReference(BaseModel):
    """Reference to a wire harness included in the production batch."""
    harness_id: str
    harness_part_number: str
    station_id: str
    cdm_source: Optional[str] = None
    layout_source: Optional[str] = None


class ProductionBillOfProcess(BaseModel):
    """Top-level Bill of Process for a production batch.

    Contains references to one or more harnesses and the complete
    ordered list of assembly phases with their process steps.
    """
    production_id: str
    created_at: datetime
    harness_refs: List[HarnessReference] = Field(default_factory=list)
    phases: List[AssemblyPhase] = Field(default_factory=list)
