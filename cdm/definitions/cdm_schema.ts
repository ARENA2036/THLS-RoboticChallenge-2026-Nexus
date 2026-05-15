/* Auto-generated from cdm_schema.py - DO NOT EDIT */

export interface CdmSchema {
  id: string;
  part_number: string;
  version?: string | null;
  company_name?: string | null;
  description?: string | null;
  created_at: string;
  modified_at?: string | null;
  connectors?: Connector[];
  terminals?: Terminal[];
  wires?: Wire[];
  wire_protections?: WireProtection[];
  accessories?: Accessory[];
  fixings?: Fixing[];
  connector_occurrences?: ConnectorOccurrence[];
  wire_occurrences?: WireOccurrence[];
  special_wire_occurrences?: SpecialWireOccurrence[];
  wire_protection_occurrences?: WireProtectionOccurrence[];
  accessory_occurrences?: AccessoryOccurrence[];
  fixing_occurrences?: FixingOccurrence[];
  connections?: Connection[];
  nodes?: Node[];
  segments?: Segment[];
  routings?: Routing[];
  [k: string]: unknown;
}
export interface Connector {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  connector_type: "housing" | "module" | "inline" | "splice" | "terminal_block";
  housing_color?: string | null;
  housing_code?: string | null;
  material?: string | null;
  mass_g?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  slots?: Slot[];
  [k: string]: unknown;
}
export interface Slot {
  id: string;
  slot_number: string;
  num_cavities: number;
  cavities?: Cavity[];
  gender?: "male" | "female" | "na";
  [k: string]: unknown;
}
export interface Cavity {
  id: string;
  cavity_number: string;
  is_available?: boolean;
  has_integrated_terminal?: boolean;
  [k: string]: unknown;
}
export interface Terminal {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  terminal_type: "pin" | "socket" | "ring" | "spade" | "blade" | "splice";
  gender?: "male" | "female" | "na";
  min_cross_section_mm?: number | null;
  max_cross_section_mm?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  [k: string]: unknown;
}
export interface Wire {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  wire_type: "wire" | "cable" | "twisted_pair" | "coaxial" | "shielded" | "multi_core";
  cross_section_area_mm2?: number | null;
  outside_diameter?: number | null;
  material_conductor?: string | null;
  material_insulation?: string | null;
  mass_g?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  cover_colors?: WireColor[];
  cores?: Core[];
  [k: string]: unknown;
}
export interface WireColor {
  color_type: string;
  color_code: string;
  [k: string]: unknown;
}
/**
 * Individual core within a multi-core cable definition.
 */
export interface Core {
  id: string;
  label?: string | null;
  wire_type?: string | null;
  cross_section_area_mm2?: number | null;
  outside_diameter_mm?: number | null;
  colors?: WireColor[];
  cable_designator?: string | null;
  [k: string]: unknown;
}
/**
 * Definition of wire protection material (tape, tube, conduit, etc.).
 */
export interface WireProtection {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  protection_type?: ("tape" | "tube" | "conduit" | "sleeve" | "grommet") | null;
  material?: string | null;
  mass_g?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  [k: string]: unknown;
}
/**
 * Definition of an accessory component (e.g., hybrid housing assemblies).
 */
export interface Accessory {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  accessory_type?: string | null;
  material?: string | null;
  mass_g?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  [k: string]: unknown;
}
/**
 * Definition of a fixing component (cable ties, clips, etc.).
 */
export interface Fixing {
  id: string;
  part_number: string;
  manufacturer?: string | null;
  description?: string | null;
  fixing_type?: string | null;
  material?: string | null;
  mass_g?: number | null;
  unit_price?: number | null;
  currency?: string | null;
  digikey_url?: string | null;
  [k: string]: unknown;
}
export interface ConnectorOccurrence {
  id: string;
  connector: Connector;
  label?: string | null;
  description?: string | null;
  position?: CartesianPoint | null;
  slots?: Slot[];
  contact_points?: ContactPoint[];
  [k: string]: unknown;
}
export interface CartesianPoint {
  id?: string | null;
  coord_x: number;
  coord_y: number;
  coord_z?: number;
  [k: string]: unknown;
}
export interface ContactPoint {
  id: string;
  terminal: Terminal;
  cavity: Cavity;
  [k: string]: unknown;
}
/**
 * Instance of a simple wire.
 */
export interface WireOccurrence {
  id: string;
  wire: Wire;
  wire_number?: string | null;
  length?: WireLength | null;
  length_dmu?: number | null;
  length_production?: number | null;
  printed_label?: string | null;
  [k: string]: unknown;
}
/**
 * Length specification with type descriptor.
 */
export interface WireLength {
  length_type: string;
  length_mm: number;
  [k: string]: unknown;
}
/**
 * Instance of a multi-core/coaxial/shielded cable with nested core occurrences.
 */
export interface SpecialWireOccurrence {
  id: string;
  wire: Wire;
  special_wire_id?: string | null;
  length?: WireLength | null;
  core_occurrences?: CoreOccurrence[];
  [k: string]: unknown;
}
/**
 * Instance of a core within a special wire occurrence.
 */
export interface CoreOccurrence {
  id: string;
  core: Core;
  wire_number?: string | null;
  length?: WireLength | null;
  [k: string]: unknown;
}
/**
 * Instance of wire protection used in the harness.
 */
export interface WireProtectionOccurrence {
  id: string;
  protection: WireProtection;
  label?: string | null;
  [k: string]: unknown;
}
/**
 * Instance of an accessory used in the harness.
 */
export interface AccessoryOccurrence {
  id: string;
  accessory: Accessory;
  label?: string | null;
  position?: CartesianPoint | null;
  referenced_connectors?: Connector[];
  [k: string]: unknown;
}
/**
 * Instance of a fixing used in the harness.
 */
export interface FixingOccurrence {
  id: string;
  fixing: Fixing;
  label?: string | null;
  position?: CartesianPoint | null;
  [k: string]: unknown;
}
export interface Connection {
  id: string;
  signal_name?: string | null;
  wire_occurrence: WireOccurrence | CoreOccurrence;
  extremities?: Extremity[];
  segments?: Segment[];
  [k: string]: unknown;
}
export interface Extremity {
  id?: string | null;
  position_on_wire: number;
  contact_point: ContactPoint;
  [k: string]: unknown;
}
export interface Segment {
  id: string;
  label?: string | null;
  start_node: Node;
  end_node: Node;
  length?: number | null;
  virtual_length?: number | null;
  physical_length?: number | null;
  center_curve?: BezierCurve | null;
  protection_areas?: ProtectionArea[];
  min_bend_radius_mm?: number | null;
  fixings?: FixingOccurrence[];
  [k: string]: unknown;
}
export interface Node {
  id: string;
  label?: string | null;
  position: CartesianPoint;
  [k: string]: unknown;
}
export interface BezierCurve {
  id?: string | null;
  degree: number;
  control_points: CartesianPoint[];
  [k: string]: unknown;
}
/**
 * Defines where wire protection is applied on a segment.
 */
export interface ProtectionArea {
  id?: string | null;
  start_location: number;
  end_location: number;
  wire_protection_occurrence: WireProtectionOccurrence;
  [k: string]: unknown;
}
export interface Routing {
  id?: string | null;
  routed_connection: Connection;
  segments: Segment[];
  [k: string]: unknown;
}
