import logging
import json
import re
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel
from public.cdm.definitions.cdm_schema import WireHarness, ConnectorOccurrence, WireOccurrence, Terminal, Wire, Connector, Slot, Cavity

logger = logging.getLogger(__name__)
if not logger.handlers:
    fh = logging.FileHandler('vlm_parsing.log')
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)

class CDMValidator:
    def __init__(self):
        self.report = {
            "errors": [],
            "warnings": [],
            "stats": {"checked_components": 0}
        }

    def validate(self, harness: WireHarness) -> Dict[str, Any]:
        """
        Runs full validation suite on the Harness.
        """
        self.report = {"errors": [], "warnings": [], "stats": {"checked_components": 0}}
        
        self._validate_connectors(harness.connector_occurrences)
        self._validate_wires(harness.connections)
        self._validate_ids_and_refs(harness)
        self._validate_topology(harness)
        
        return self.report

    def _validate_connectors(self, connectors: List[ConnectorOccurrence]):
        for conn_occ in connectors:
            self.report["stats"]["checked_components"] += 1
            cid = conn_occ.id
            connector = conn_occ.connector
            
            # 1. Structural Integrity
            if not conn_occ.contact_points and not conn_occ.slots:
                 self.report["warnings"].append(f"Connector '{cid}' has no contact points or slots defined.")

            # 2. Part Number Completeness
            if not connector.part_number or connector.part_number in ["Unknown", "null", None]:
                self.report["warnings"].append(f"Connector '{cid}' missing Part Number.")

            # 3. Position Completeness
            if not conn_occ.position:
                self.report["warnings"].append(f"Connector '{cid}' missing 3D Position.")

            # 4. Cavity Range / Validity Check
            self._check_cavity_range(conn_occ, connector)
            
            # Check Terminals within
            for cp in conn_occ.contact_points:
                self._validate_terminal(cp.terminal, f"{cid}.{cp.cavity.cavity_number}")

    def _check_cavity_range(self, conn_occ: ConnectorOccurrence, connector: Connector):
        """
        Verifies that used cavities in contact_points exist in the connector definition (slots).
        Also flags generically 'high' numbers if slots are undefined but numbers seem odd (heuristic).
        """
        # Collect all valid cavity numbers from the Connector definition
        valid_cavities: Set[str] = set()
        max_numeric_cavity = 0
        
        for slot in connector.slots:
            for cav in slot.cavities:
                valid_cavities.add(cav.cavity_number)
                # Track max numeric for heuristic check
                if cav.cavity_number.isdigit():
                    val = int(cav.cavity_number)
                    if val > max_numeric_cavity: max_numeric_cavity = val

        # If connector has slots defined, we enforce strict validity
        has_slots_def = len(valid_cavities) > 0

        for cp in conn_occ.contact_points:
            cav_num = cp.cavity.cavity_number
            
            # Strict Check: If we know the allowed cavities, instant fail if not in set
            if has_slots_def:
                if cav_num not in valid_cavities:
                    self.report["errors"].append(
                        f"Cavity Violation: Connector '{conn_occ.id}' uses cavity '{cav_num}' which is not listed in definition ({list(valid_cavities)})."
                    )
            
            # Heuristic Check: If no slots defined (e.g. ad-hoc connector), check for suspicious high numbers
            # Assuming standard auto connectors rarely go above 128 pins without being modules
            else:
                 if cav_num.isdigit() and int(cav_num) > 200:
                      self.report["warnings"].append(
                        f"Suspicious Cavity: Connector '{conn_occ.id}' uses high cavity number '{cav_num}' but has no slot definition."
                    )

    def _validate_terminal(self, terminal: Terminal, context: str):
        if not terminal.part_number or terminal.part_number in ["Unknown", "null", None]:
             self.report["warnings"].append(f"Terminal at '{context}' missing Part Number.")

    def _validate_wires(self, connections: List):
        for conn in connections:
            self.report["stats"]["checked_components"] += 1
            wire_occ = conn.wire_occurrence
            
            if isinstance(wire_occ, WireOccurrence):
                wid = wire_occ.id
                wire = wire_occ.wire
                
                # 1. Part Number Completeness
                if not wire.part_number or wire.part_number in ["Unknown", "null", None]:
                    self.report["warnings"].append(f"Wire '{wid}' missing Part Number.")

                # 2. Length Sanity
                length_val = None
                if wire_occ.length and wire_occ.length.length_mm:
                    length_val = wire_occ.length.length_mm
                elif wire_occ.length_production:
                    length_val = wire_occ.length_production
                elif wire_occ.length_dmu:
                    length_val = wire_occ.length_dmu
                
                if length_val is None:
                    self.report["warnings"].append(f"Wire '{wid}' has no length defined.")
                elif length_val <= 0:
                    self.report["errors"].append(f"Wire '{wid}' has invalid length: {length_val}")

                # 3. Electrical Compatibility (Crimping)
                for ext in conn.extremities:
                    if ext.contact_point and ext.contact_point.terminal:
                        term = ext.contact_point.terminal
                        self._check_crimping(wire, term, wid, term.id)



    def _check_crimping(self, wire: Wire, terminal: Terminal, wire_id: str, term_id: str):
        """
        Verifies if wire cross-section fits in terminal range.
        """
        w_csa = wire.cross_section_area_mm2
        t_min = terminal.min_cross_section_mm
        t_max = terminal.max_cross_section_mm
        
        if w_csa is None:
            # self.report["warnings"].append(f"Wire '{wire_id}' missing cross-section for crimp check.")
            return

        if t_min is None or t_max is None:
            return

        # Simple range check
        # Use a small tolerance for floating point comparisons
        if w_csa < (t_min - 0.001) or w_csa > (t_max + 0.001):
            self.report["errors"].append(
                f"Crimping Violation: Wire '{wire_id}' (CSA {w_csa}) does not fit Terminal '{term_id}' "
                f"range [{t_min} - {t_max}]."
            )

    def _validate_ids_and_refs(self, harness: WireHarness):
        """
        Checks global ID uniqueness and definition references.
        """
        seen_ids = set()
        
        # Helper to check ID uniqueness
        def check_id(obj_id, obj_type):
            if not obj_id: return
            if obj_id in seen_ids:
                self.report["errors"].append(f"Duplicate ID found: '{obj_id}' (Type: {obj_type})")
            seen_ids.add(obj_id)

        # 1. Check Key Definitions
        valid_connector_ids = {c.id for c in harness.connectors}
        valid_wire_ids = {w.id for w in harness.wires}
        
        # 2. Check Occurrences against Definitions
        for co in harness.connector_occurrences:
            check_id(co.id, "ConnectorOccurrence")
            # Ref Check
            if co.connector.id not in valid_connector_ids:
                 self.report["errors"].append(f"Reference Error: ConnectorOccurrence '{co.id}' refers to unknown Connector Def '{co.connector.id}'")

        for conn in harness.connections:
            check_id(conn.id, "Connection")
            if isinstance(conn.wire_occurrence, WireOccurrence):
                wo = conn.wire_occurrence
                check_id(wo.id, "WireOccurrence")
                if wo.wire.id not in valid_wire_ids:
                     self.report["errors"].append(f"Reference Error: WireOccurrence '{wo.id}' refers to unknown Wire Def '{wo.wire.id}'")
        
        for segment in harness.segments:
            check_id(segment.id, "Segment")
            
        for node in harness.nodes:
            check_id(node.id, "Node")

    def _validate_topology(self, harness: WireHarness):
        """
        Checks segment nodes and connection structure.
        """
        valid_node_ids = {n.id for n in harness.nodes}
        
        for segment in harness.segments:
            if segment.start_node.id not in valid_node_ids:
                self.report["errors"].append(f"Topology Error: Segment '{segment.id}' start_node '{segment.start_node.id}' not in harness.nodes")
            if segment.end_node.id not in valid_node_ids:
                 self.report["errors"].append(f"Topology Error: Segment '{segment.id}' end_node '{segment.end_node.id}' not in harness.nodes")

        for conn in harness.connections:
            # Simple wires should have at least 2 extremities
            if len(conn.extremities) < 2:
                 self.report["warnings"].append(f"Topology Warning: Connection '{conn.id}' has fewer than 2 extremities.")
