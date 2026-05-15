"""Render extracted WiringDiagrams (and their ground-truth WireHarnesses)
to PDFs for visual comparison.

Under eval/output/runs/<case>/:
  first_pass.json    -> <case>_pred.pdf
  ground_truth.json  -> <case>_gt.pdf     (when --gt is set, default on)

Layout reuses eval.render.pdf_renderer.render_harness_to_pdf; the extractor's
WiringDiagram is shimmed into a WireHarness with synthesized terminals,
cavities, contact points, wire occurrences, and connections.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import (
    Cavity,
    Connection,
    Connector as CdmConnector,
    ConnectorOccurrence,
    ContactPoint,
    Extremity,
    Terminal,
    Wire as CdmWire,
    WireColor as CdmWireColor,
    WireHarness,
    WireOccurrence,
)
from eval.config import NAME_TO_IEC
from eval.render.pdf_renderer import render_harness_to_pdf
from parsing.util.structure import WiringDiagram


_GENERIC_TERMINAL = Terminal(
    id="term_generic",
    part_number="GENERIC",
    terminal_type="pin",
    gender="na",
)


def wiring_diagram_to_wireharness(
    diagram: WiringDiagram,
    harness_id: str = "wd_wrap",
) -> WireHarness:
    """Wrap an extractor WiringDiagram as a CDM WireHarness for rendering."""
    cdm_connectors: List[CdmConnector] = []
    occurrences: List[ConnectorOccurrence] = []
    cp_index: Dict[Tuple[str, int], ContactPoint] = {}

    for c in diagram.connectors:
        listed = {p.pin_number for p in c.pins}
        pin_numbers = sorted(listed)
        if c.pin_count and c.pin_count > len(pin_numbers):
            for n in range(1, c.pin_count + 1):
                if n not in listed:
                    pin_numbers.append(n)
            pin_numbers.sort()

        cdm_conn = CdmConnector(
            id=f"conn_{c.connector_id}",
            part_number=c.connector_name or "",
            connector_type="housing",
        )
        cdm_connectors.append(cdm_conn)

        cps: List[ContactPoint] = []
        for pn in pin_numbers:
            cav = Cavity(
                id=f"cav_{c.connector_id}_{pn}",
                cavity_number=str(pn),
            )
            cp = ContactPoint(
                id=f"cp_{c.connector_id}_{pn}",
                terminal=_GENERIC_TERMINAL,
                cavity=cav,
            )
            cps.append(cp)
            cp_index[(c.connector_id, pn)] = cp

        occurrences.append(ConnectorOccurrence(
            id=f"occ_{c.connector_id}",
            connector=cdm_conn,
            label=c.connector_id,
            contact_points=cps,
        ))

    cdm_wires: List[CdmWire] = []
    wire_occurrences: List[WireOccurrence] = []
    connections: List[Connection] = []

    for w in diagram.wires:
        color_val = w.color.value if hasattr(w.color, "value") else str(w.color)
        iec = NAME_TO_IEC.get(color_val, "??")

        cdm_wire = CdmWire(
            id=f"wire_{w.wire_id}",
            part_number=w.part_number or "",
            wire_type="wire",
            cross_section_area_mm2=w.gauge,
            cover_colors=[CdmWireColor(color_type="Base Color", color_code=iec)],
        )
        cdm_wires.append(cdm_wire)
        wo = WireOccurrence(
            id=f"wo_{w.wire_id}",
            wire=cdm_wire,
            wire_number=w.wire_id,
        )
        wire_occurrences.append(wo)

        src = cp_index.get((w.source_connector_id, w.source_pin_number))
        dst = cp_index.get((w.destination_connector_id, w.destination_pin_number))
        extremities: List[Extremity] = []
        if src is not None:
            extremities.append(Extremity(position_on_wire=0.0, contact_point=src))
        if dst is not None:
            extremities.append(Extremity(position_on_wire=1.0, contact_point=dst))

        connections.append(Connection(
            id=f"c_{w.wire_id}",
            wire_occurrence=wo,
            extremities=extremities,
        ))

    created_at = diagram.created_at.isoformat() if diagram.created_at else ""
    return WireHarness(
        id=harness_id,
        part_number=diagram.diagram_id or harness_id,
        version=diagram.version,
        created_at=created_at,
        connectors=cdm_connectors,
        wires=cdm_wires,
        connector_occurrences=occurrences,
        wire_occurrences=wire_occurrences,
        connections=connections,
    )


def render_extracted_to_pdf(pred_json: Path, output_pdf: Path) -> Path:
    diagram = WiringDiagram.model_validate(json.loads(pred_json.read_text()))
    harness = wiring_diagram_to_wireharness(diagram, harness_id=pred_json.stem)
    render_harness_to_pdf(harness, output_pdf)
    return output_pdf


def main():
    ap = argparse.ArgumentParser(
        description="Render extracted WiringDiagram + GT WireHarness to PDFs.",
    )
    ap.add_argument("runs_dir", type=Path,
                    help="Directory with per-case subdirs (first_pass.json, ground_truth.json).")
    ap.add_argument("-o", "--output-dir", type=Path, default=None,
                    help="Output directory (default: <runs_dir>/../pdfs).")
    ap.add_argument("--no-gt", action="store_true",
                    help="Skip rendering ground_truth.json.")
    ap.add_argument("--no-pred", action="store_true",
                    help="Skip rendering first_pass.json.")
    args = ap.parse_args()

    out_dir = args.output_dir or args.runs_dir.parent / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)

    ok_pred = ok_gt = err = 0
    for cdir in sorted(p for p in args.runs_dir.iterdir() if p.is_dir()):
        cid = cdir.name

        if not args.no_pred:
            pred_path = cdir / "first_pass.json"
            if pred_path.exists():
                try:
                    render_extracted_to_pdf(pred_path, out_dir / f"{cid}_pred.pdf")
                    ok_pred += 1
                except Exception as exc:
                    print(f"  ERR {cid} pred: {exc}")
                    err += 1

        if not args.no_gt:
            gt_path = cdir / "ground_truth.json"
            if gt_path.exists():
                try:
                    harness = WireHarness.model_validate(json.loads(gt_path.read_text()))
                    render_harness_to_pdf(harness, out_dir / f"{cid}_gt.pdf")
                    ok_gt += 1
                except Exception as exc:
                    print(f"  ERR {cid} gt: {exc}")
                    err += 1

    print(f"\n{ok_pred} pred, {ok_gt} gt rendered, {err} errors -> {out_dir}")


if __name__ == "__main__":
    main()
