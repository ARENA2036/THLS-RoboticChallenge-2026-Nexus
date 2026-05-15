"""
Central registry of IDTA semantic IRIs used across all AAS submodels.

All IRIs follow the admin-shell.io namespace conventions.
Custom project-specific IRIs use the urn:NEXUS: namespace.

References:
  IDTA 02006-2-0: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Digital%20Nameplate
  IDTA 02011-1-1: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Hierarchical%20Structures%20enabling%20Bills%20of%20Material
  IDTA 02020-1-0: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Capability%20Description
  IDTA 02031-1-0: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Process%20Parameters%20Type
"""


# ===========================================================================
# IDTA 02006-2-0 — Digital Nameplate for Industrial Equipment
# ===========================================================================

class DigitalNameplate:
    SUBMODEL = "https://admin-shell.io/IDTA/02006-2-0/Submodel/DigitalNameplate"

    # Properties (IRDI-based semantic IDs from IDTA 02006-2-0 spec)
    MANUFACTURER_NAME = "https://admin-shell.io/IDTA/02006-2-0/ContactInformation/ManufacturerName"
    MANUFACTURER_PRODUCT_DESIGNATION = "https://admin-shell.io/IDTA/02006-2-0/General/ManufacturerProductDesignation"
    MANUFACTURER_PART_NUMBER = "https://admin-shell.io/IDTA/02006-2-0/General/ManufacturerPartNumber"
    MANUFACTURER_PRODUCT_FAMILY = "https://admin-shell.io/IDTA/02006-2-0/General/ManufacturerProductFamily"
    MANUFACTURER_PRODUCT_TYPE = "https://admin-shell.io/IDTA/02006-2-0/General/ManufacturerProductType"
    SERIAL_NUMBER = "https://admin-shell.io/IDTA/02006-2-0/General/SerialNumber"
    BATCH_NUMBER = "https://admin-shell.io/IDTA/02006-2-0/General/BatchNumber"
    PRODUCT_COUNTRY_OF_ORIGIN = "https://admin-shell.io/IDTA/02006-2-0/General/ProductCountryOfOrigin"
    YEAR_OF_CONSTRUCTION = "https://admin-shell.io/IDTA/02006-2-0/General/YearOfConstruction"
    DATE_OF_MANUFACTURE = "https://admin-shell.io/IDTA/02006-2-0/General/DateOfManufacture"
    HARDWARE_VERSION = "https://admin-shell.io/IDTA/02006-2-0/General/HardwareVersion"
    FIRMWARE_VERSION = "https://admin-shell.io/IDTA/02006-2-0/General/FirmwareVersion"
    SOFTWARE_VERSION = "https://admin-shell.io/IDTA/02006-2-0/General/SoftwareVersion"
    URI_OF_THE_PRODUCT = "https://admin-shell.io/IDTA/02006-2-0/General/URIOfTheProduct"
    MARKINGS = "https://admin-shell.io/IDTA/02006-2-0/General/Markings"


# ===========================================================================
# IDTA 02011-1-1 — Hierarchical Structures enabling BOM
# ===========================================================================

class HierarchicalBOM:
    SUBMODEL = "https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel"
    ENTRY_NODE = "https://admin-shell.io/idta/HierarchicalStructures/1/1/EntryNode"
    NODE = "https://admin-shell.io/idta/HierarchicalStructures/1/1/Node"
    SAME_AS = "https://admin-shell.io/idta/HierarchicalStructures/1/1/SameAs"
    PART_OF = "https://admin-shell.io/idta/HierarchicalStructures/1/1/PartOf"
    IS_PART = "https://admin-shell.io/idta/HierarchicalStructures/1/1/IsPart"
    ARCHE_TYPE = "https://admin-shell.io/idta/HierarchicalStructures/1/1/ArcheType"
    # ArcheType values
    ARCHE_TYPE_FULL = "Full"
    ARCHE_TYPE_ONE_DOWN = "OneDown"
    ARCHE_TYPE_ONE_UP = "OneUp"


# ===========================================================================
# IDTA 02020-1-0 — Capability Description
# ===========================================================================

class CapabilityDescription:
    SUBMODEL = "https://admin-shell.io/IDTA/02020-1-0/Submodel/CapabilityDescription"
    CAPABILITY_SET = "https://admin-shell.io/IDTA/02020-1-0/CapabilitySet"
    CAPABILITY = "https://admin-shell.io/IDTA/02020-1-0/Capability"
    CAPABILITY_PROPERTY = "https://admin-shell.io/IDTA/02020-1-0/CapabilityProperty"
    PROPERTY_NAME = "https://admin-shell.io/IDTA/02020-1-0/PropertyName"
    PROPERTY_VALUE = "https://admin-shell.io/IDTA/02020-1-0/PropertyValue"
    PROPERTY_CONDITION = "https://admin-shell.io/IDTA/02020-1-0/PropertyCondition"
    # Condition values
    CONDITION_REQUIRED = "Required"
    CONDITION_OPTIONAL = "Optional"
    CONDITION_NONE = "None"


# ===========================================================================
# IDTA 02031-1-0 — Process Parameters Type
# ===========================================================================

class ProcessParametersType:
    SUBMODEL = "https://admin-shell.io/IDTA/02031-1-0/Submodel/ProcessParametersType"
    PROCESS_TYPE = "https://admin-shell.io/IDTA/02031-1-0/ProcessType"
    PROCESS_STEP = "https://admin-shell.io/IDTA/02031-1-0/ProcessStep"
    PROCESS_PARAMETERS = "https://admin-shell.io/IDTA/02031-1-0/ProcessParameters"
    PROCESS_PARAMETER = "https://admin-shell.io/IDTA/02031-1-0/ProcessParameter"
    PROCESS_PARAMETER_NAME = "https://admin-shell.io/IDTA/02031-1-0/ProcessParameterName"
    PROCESS_PARAMETER_VALUE = "https://admin-shell.io/IDTA/02031-1-0/ProcessParameterValue"
    ASSEMBLY_PHASE = "https://admin-shell.io/IDTA/02031-1-0/AssemblyPhase"
    SEQUENCE_NUMBER = "https://admin-shell.io/IDTA/02031-1-0/SequenceNumber"
    ESTIMATED_DURATION = "https://admin-shell.io/IDTA/02031-1-0/EstimatedDuration"
    DEPENDS_ON = "https://admin-shell.io/IDTA/02031-1-0/DependsOn"
    STATION_ID = "https://admin-shell.io/IDTA/02031-1-0/StationId"
    HARNESS_ID = "https://admin-shell.io/IDTA/02031-1-0/HarnessId"


# ===========================================================================
# Project-specific custom submodel IRIs  (urn:NEXUS:submodel:…)
# ===========================================================================

class CDMTopology:
    SUBMODEL = "urn:NEXUS:submodel:CDMTopology:1-0"
    NODE = "urn:NEXUS:cdm:Node"
    SEGMENT = "urn:NEXUS:cdm:Segment"
    CONNECTION = "urn:NEXUS:cdm:Connection"
    ROUTING = "urn:NEXUS:cdm:Routing"
    EXTREMITY = "urn:NEXUS:cdm:Extremity"
    PROTECTION_AREA = "urn:NEXUS:cdm:ProtectionArea"


class WorkcellConfiguration:
    SUBMODEL = "urn:NEXUS:submodel:WorkcellConfiguration:1-0"
    BOARD = "urn:NEXUS:workcell:Board"
    ROBOT = "urn:NEXUS:workcell:Robot"
    GRIPPER = "urn:NEXUS:workcell:Gripper"
    PEG_SHAPE = "urn:NEXUS:workcell:PegShape"
    WORKSPACE_ZONE = "urn:NEXUS:workcell:WorkspaceZone"


class TechnicalProperties:
    SUBMODEL = "urn:NEXUS:submodel:TechnicalProperties:1-0"
    # Connector
    CONNECTOR_TYPE = "urn:NEXUS:component:ConnectorType"
    HOUSING_COLOR = "urn:NEXUS:component:HousingColor"
    HOUSING_CODE = "urn:NEXUS:component:HousingCode"
    SLOT = "urn:NEXUS:component:Slot"
    CAVITY = "urn:NEXUS:component:Cavity"
    # Wire
    WIRE_TYPE = "urn:NEXUS:component:WireType"
    CROSS_SECTION_MM2 = "urn:NEXUS:component:CrossSectionMm2"
    OUTSIDE_DIAMETER_MM = "urn:NEXUS:component:OutsideDiameterMm"
    CONDUCTOR_MATERIAL = "urn:NEXUS:component:ConductorMaterial"
    INSULATION_MATERIAL = "urn:NEXUS:component:InsulationMaterial"
    COVER_COLOR = "urn:NEXUS:component:CoverColor"
    # Terminal
    TERMINAL_TYPE = "urn:NEXUS:component:TerminalType"
    GENDER = "urn:NEXUS:component:Gender"
    MIN_CROSS_SECTION_MM2 = "urn:NEXUS:component:MinCrossSectionMm2"
    MAX_CROSS_SECTION_MM2 = "urn:NEXUS:component:MaxCrossSectionMm2"
    # WireProtection
    PROTECTION_TYPE = "urn:NEXUS:component:ProtectionType"
    # Fixing / Accessory
    FIXING_TYPE = "urn:NEXUS:component:FixingType"
    ACCESSORY_TYPE = "urn:NEXUS:component:AccessoryType"
    # Shared
    MATERIAL = "urn:NEXUS:component:Material"
    MASS_G = "urn:NEXUS:component:MassG"
    UNIT_PRICE = "urn:NEXUS:component:UnitPrice"
    CURRENCY = "urn:NEXUS:component:Currency"
    PART_NUMBER = "urn:NEXUS:component:PartNumber"
    MANUFACTURER = "urn:NEXUS:component:Manufacturer"


# ===========================================================================
# AssemblyBoardLayout  (urn:NEXUS:submodel:AssemblyBoardLayout:1-0)
# ===========================================================================

class AssemblyBoardLayout:
    SUBMODEL = "urn:NEXUS:submodel:AssemblyBoardLayout:1-0"
    PEG_POSITION = "urn:NEXUS:layout:PegPosition"
    CONNECTOR_HOLDER_POSITION = "urn:NEXUS:layout:ConnectorHolderPosition"
    LAYOUT_METRICS = "urn:NEXUS:layout:LayoutMetrics"
    BOARD_CONFIG = "urn:NEXUS:layout:BoardConfig"


# ===========================================================================
# MaterialDelivery  (urn:NEXUS:submodel:MaterialDelivery:1-0)
# ===========================================================================

class MaterialDelivery:
    SUBMODEL = "urn:NEXUS:submodel:MaterialDelivery:1-0"
    WIRE_END_PICKUP = "urn:NEXUS:material:WireEndPickup"
    OBJECT_PICKUP = "urn:NEXUS:material:ObjectPickup"
    PICKUP_PARAMETERS = "urn:NEXUS:material:PickupParameters"


# ===========================================================================
# WorkspaceZones  (urn:NEXUS:submodel:WorkspaceZones:1-0)
# ===========================================================================

class WorkspaceZones:
    SUBMODEL = "urn:NEXUS:submodel:WorkspaceZones:1-0"
    PICKUP_ZONE = "urn:NEXUS:workspace:PickupZone"
    BOARD_HALF = "urn:NEXUS:workspace:BoardHalf"
    ROBOT_ASSIGNMENT = "urn:NEXUS:workspace:RobotAssignment"
    SAFETY_POLICY = "urn:NEXUS:workspace:SafetyPolicy"


# ===========================================================================
# ExecutionTrace  (urn:NEXUS:submodel:ExecutionTrace:1-0)
# ===========================================================================

class ExecutionTrace:
    SUBMODEL = "urn:NEXUS:submodel:ExecutionTrace:1-0"
    STEP_OUTCOME = "urn:NEXUS:execution:StepOutcome"
    ROBOT_TRACE = "urn:NEXUS:execution:RobotTrace"
    ROBOT_ERROR = "urn:NEXUS:execution:RobotError"
    TCP_WAYPOINT = "urn:NEXUS:execution:TcpWaypoint"


# ===========================================================================
# PreFabBillOfProcess  (urn:NEXUS:submodel:PreFabBillOfProcess:1-0)
# OPC 40570 (Wire Harness Manufacturing) process types
# ===========================================================================

class PreFabBillOfProcess:
    SUBMODEL = "urn:NEXUS:submodel:PreFabBillOfProcess:1-0"
    # OPC 40570 process type IRIs (approximated — pending official OPC publication)
    OPC40570_CUT = "urn:opcfoundation:opc40570:ProcessType:Cut"
    OPC40570_STRIP = "urn:opcfoundation:opc40570:ProcessType:Strip"
    OPC40570_CRIMP = "urn:opcfoundation:opc40570:ProcessType:Crimp"
    OPC40570_SEAL = "urn:opcfoundation:opc40570:ProcessType:Seal"
    # Parameters
    CUT_LENGTH_MM = "urn:NEXUS:prefab:CutLengthMm"
    STRIP_LENGTH_MM = "urn:NEXUS:prefab:StripLengthMm"
    CRIMP_FORCE_N = "urn:NEXUS:prefab:CrimpForceN"
    WIRE_OCCURRENCE_ID = "urn:NEXUS:prefab:WireOccurrenceId"
    EXTREMITY_INDEX = "urn:NEXUS:prefab:ExtremityIndex"


# ===========================================================================
# ProductionOrder  (urn:NEXUS:submodel:ProductionOrder:1-0)
# ===========================================================================

class ProductionOrder:
    SUBMODEL = "urn:NEXUS:submodel:ProductionOrder:1-0"
    ORDER_NUMBER = "urn:NEXUS:order:OrderNumber"
    PRODUCTION_QUANTITY = "urn:NEXUS:order:ProductionQuantity"
    TARGET_DELIVERY_DATE = "urn:NEXUS:order:TargetDeliveryDate"
    STATUS = "urn:NEXUS:order:Status"
    HARNESS_VARIANT_REF = "urn:NEXUS:order:HarnessVariantRef"
    BOP_REF = "urn:NEXUS:order:BoPRef"
    STATION_REF = "urn:NEXUS:order:StationRef"
