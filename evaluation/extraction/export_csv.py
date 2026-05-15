#!/usr/bin/env python3
"""Export a completed eval run to CSVs.

Produces five CSVs under <out>/csv/:

  summary.csv          one row per case:  case_id, n_gt_connectors, n_gt_wires,
                       n_pred_connectors, n_pred_wires, extraction_ok
  gt_connectors.csv    one row per ground-truth connector occurrence
  gt_wires.csv         one row per ground-truth connection (wire)
  pred_connectors.csv  one row per extracted connector
  pred_wires.csv       one row per extracted wire

All five share `case_id` for joining. From these you can recompute any
connector / connectivity F1, pin-count accuracy, or endpoint-pair accuracy.

Usage:
    python eval/export_csv.py --runs-dir eval/output/runs
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import WireHarness
from parsing.util.structure import WiringDiagram


def _load_pred(path: Path) -> Optional[WiringDiagram]:
    if not path.exists():
        return None
    try:
        return WiringDiagram.model_validate(json.loads(path.read_text()))
    except Exception:
        return None


def _load_gt(path: Path) -> Optional[WireHarness]:
    if not path.exists():
        return None
    try:
        return WireHarness.model_validate(json.loads(path.read_text()))
    except Exception:
        return None


def _wo_part_number(wo) -> str:
    wire = getattr(wo, "wire", None)
    if wire is not None and getattr(wire, "part_number", None):
        return wire.part_number
    core = getattr(wo, "core", None)
    if core is not None and getattr(core, "part_number", None):
        return core.part_number
    return ""


def export(runs_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict[str, Any]] = []
    gt_conn_rows: List[Dict[str, Any]] = []
    gt_wire_rows: List[Dict[str, Any]] = []
    pred_conn_rows: List[Dict[str, Any]] = []
    pred_wire_rows: List[Dict[str, Any]] = []

    cases = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    for cdir in cases:
        case_id = cdir.name
        gt = _load_gt(cdir / "ground_truth.json")
        pred = _load_pred(cdir / "first_pass.json")

        n_gt_conn = len(gt.connector_occurrences) if gt else 0
        n_gt_wire = len(gt.connections) if gt else 0
        n_pred_conn = len(pred.connectors) if pred else 0
        n_pred_wire = len(pred.wires) if pred else 0

        summary_rows.append({
            "case_id": case_id,
            "n_gt_connectors": n_gt_conn,
            "n_gt_wires": n_gt_wire,
            "n_pred_connectors": n_pred_conn,
            "n_pred_wires": n_pred_wire,
            "extraction_ok": int(pred is not None),
        })

        if gt is not None:
            # Build contact_point.id -> owning connector's part_number + label
            cp_to_part: Dict[str, str] = {}
            cp_to_label: Dict[str, str] = {}
            for occ in gt.connector_occurrences:
                part = occ.connector.part_number or ""
                for cp in occ.contact_points:
                    cp_to_part[cp.id] = part
                    cp_to_label[cp.id] = occ.label or ""
                gt_conn_rows.append({
                    "case_id": case_id,
                    "occurrence_id": occ.id,
                    "label": occ.label or "",
                    "part_number": part,
                    "n_contact_points": len(occ.contact_points),
                })
            for conn in gt.connections:
                wp = _wo_part_number(conn.wire_occurrence) if conn.wire_occurrence else ""
                ex = list(conn.extremities or [])
                if len(ex) >= 2:
                    cp0, cp1 = ex[0].contact_point.id, ex[1].contact_point.id
                    src_part = cp_to_part.get(cp0, "")
                    dst_part = cp_to_part.get(cp1, "")
                    src_lbl = cp_to_label.get(cp0, "")
                    dst_lbl = cp_to_label.get(cp1, "")
                else:
                    src_part = dst_part = src_lbl = dst_lbl = ""
                gt_wire_rows.append({
                    "case_id": case_id,
                    "connection_id": conn.id,
                    "wire_part_number": wp,
                    "source_connector_label": src_lbl,
                    "source_connector_part_number": src_part,
                    "destination_connector_label": dst_lbl,
                    "destination_connector_part_number": dst_part,
                })

        if pred is not None:
            for c in pred.connectors:
                pred_conn_rows.append({
                    "case_id": case_id,
                    "connector_id": c.connector_id,
                    "connector_name": c.connector_name or "",
                    "connector_type": c.connector_type or "",
                    "pin_count": c.pin_count if c.pin_count is not None else "",
                })
            for w in pred.wires:
                pred_wire_rows.append({
                    "case_id": case_id,
                    "wire_id": w.wire_id,
                    "part_number": w.part_number or "",
                    "source_connector_id": w.source_connector_id,
                    "source_pin_number": w.source_pin_number,
                    "destination_connector_id": w.destination_connector_id,
                    "destination_pin_number": w.destination_pin_number,
                    "color": w.color if w.color else "",
                    "gauge": w.gauge if getattr(w, "gauge", None) is not None else "",
                })

    def _write(path: Path, rows: List[Dict[str, Any]]):
        if not rows:
            path.write_text("")
            return
        with path.open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)

    _write(out_dir / "summary.csv", summary_rows)
    _write(out_dir / "gt_connectors.csv", gt_conn_rows)
    _write(out_dir / "gt_wires.csv", gt_wire_rows)
    _write(out_dir / "pred_connectors.csv", pred_conn_rows)
    _write(out_dir / "pred_wires.csv", pred_wire_rows)

    print(f"Wrote CSVs to {out_dir}:")
    for name, rows in [
        ("summary.csv", summary_rows),
        ("gt_connectors.csv", gt_conn_rows),
        ("gt_wires.csv", gt_wire_rows),
        ("pred_connectors.csv", pred_conn_rows),
        ("pred_wires.csv", pred_wire_rows),
    ]:
        print(f"  {name}: {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=_REPO_ROOT / "eval" / "output" / "runs",
                    help="Directory with per-case subdirs (first_pass.json + ground_truth.json).")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Output directory (default: <runs-dir>/../csv).")
    args = ap.parse_args()

    out = args.out_dir or args.runs_dir.parent / "csv"
    export(args.runs_dir, out)


if __name__ == "__main__":
    main()
