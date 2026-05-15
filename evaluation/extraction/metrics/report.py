"""
Report builder: assembles per-case and aggregate metrics into a
human-readable Markdown table and a machine-readable JSON file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from eval.metrics.component_f1 import ConnectorMatchResult
from eval.metrics.connectivity import ConnectivityResult


# ---------------------------------------------------------------------------
# Per-case result container
# ---------------------------------------------------------------------------

@dataclass
class CaseMetrics:
    cdm_id: str                   # stem of the CDM file
    n_gt_connectors: int
    n_gt_connections: int

    fp_connector: ConnectorMatchResult
    fp_connectivity: ConnectivityResult

    enr_connector: Optional[ConnectorMatchResult]   # None if --skip-enrich
    enr_connectivity: Optional[ConnectivityResult]


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def _mean(vals: List[float]) -> float:
    finite = [v for v in vals if v is not None and not math.isnan(v)]
    return sum(finite) / len(finite) if finite else float("nan")


def _delta(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return "—"
    if math.isnan(a) or math.isnan(b):
        return "—"
    d = b - a
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.3f}"


def _fmt(v: Optional[float], pct: bool = False) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if pct:
        return f"{v:.1f}%"
    return f"{v:.3f}"


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    col_widths = [max(len(h), max((len(r[i]) for r in rows), default=0))
                  for i, h in enumerate(headers)]
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    header_row = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    data_rows = [
        "| " + " | ".join(str(r[i]).ljust(col_widths[i]) for i in range(len(headers))) + " |"
        for r in rows
    ]
    return "\n".join([header_row, sep] + data_rows)


def build_markdown_report(cases: List[CaseMetrics]) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Wire Harness Extraction Evaluation",
        f"Generated: {ts}  |  Cases: {len(cases)}",
        "",
    ]

    # ── Aggregate table ──────────────────────────────────────────────
    lines.append("## Aggregate Results")
    lines.append("")

    fp_conn_f1s  = [c.fp_connector.f1 for c in cases]
    fp_strict_f1s = [c.fp_connectivity.strict_f1 for c in cases]
    fp_loose_f1s  = [c.fp_connectivity.loose_f1 for c in cases]

    enr_conn_f1s   = [c.enr_connector.f1 if c.enr_connector else float("nan") for c in cases]
    enr_strict_f1s = [c.enr_connectivity.strict_f1 if c.enr_connectivity else float("nan") for c in cases]
    enr_loose_f1s  = [c.enr_connectivity.loose_f1 if c.enr_connectivity else float("nan") for c in cases]

    agg_rows = [
        ["Connector F1 (Part + Pin)",
         _fmt(_mean(fp_conn_f1s)), _fmt(_mean(enr_conn_f1s)),
         _delta(_mean(fp_conn_f1s), _mean(enr_conn_f1s))],
        ["Matching Connectivity F1",
         _fmt(_mean(fp_strict_f1s)), _fmt(_mean(enr_strict_f1s)),
         _delta(_mean(fp_strict_f1s), _mean(enr_strict_f1s))],
        ["Matching Name F1 (deprecated)",
         _fmt(_mean(fp_loose_f1s)), _fmt(_mean(enr_loose_f1s)),
         _delta(_mean(fp_loose_f1s), _mean(enr_loose_f1s))],
    ]
    lines.append(_md_table(
        ["Metric", "First Pass", "Enriched", "Delta"],
        agg_rows,
    ))
    lines.append("")

    # ── Per-case table ───────────────────────────────────────────────
    lines.append("## Per-Case Results")
    lines.append("")

    case_rows = []
    for cm in cases:
        enr_cf1  = _fmt(cm.enr_connector.f1 if cm.enr_connector else None)
        enr_sf1  = _fmt(cm.enr_connectivity.strict_f1 if cm.enr_connectivity else None)
        enr_lf1  = _fmt(cm.enr_connectivity.loose_f1 if cm.enr_connectivity else None)
        case_rows.append([
            cm.cdm_id,
            str(cm.n_gt_connectors),
            str(cm.n_gt_connections),
            _fmt(cm.fp_connector.f1),
            enr_cf1,
            _fmt(cm.fp_connectivity.strict_f1),
            enr_sf1,
            _fmt(cm.fp_connectivity.loose_f1),
            enr_lf1,
        ])

    lines.append(_md_table(
        ["CDM", "GT Conn", "GT Wires",
         "Conn F1 (FP)", "Conn F1 (Enr)",
         "MatchConn F1 (FP)", "MatchConn F1 (Enr)",
         "MatchName F1 (FP)", "MatchName F1 (Enr)"],
        case_rows,
    ))
    lines.append("")

    # ── Detailed per-case sections ───────────────────────────────────
    lines.append("## Detailed Results")
    lines.append("")
    for cm in cases:
        lines.append(f"### {cm.cdm_id}")
        lines.append("")
        lines.append(f"GT: {cm.n_gt_connectors} connectors, {cm.n_gt_connections} connections")
        lines.append("")

        fp = cm.fp_connector
        lines.append(f"**Connectors (First Pass):** "
                     f"P={_fmt(fp.precision)} R={_fmt(fp.recall)} F1={_fmt(fp.f1)} "
                     f"(TP={fp.tp} FP={fp.fp} FN={fp.fn})")
        if cm.enr_connector:
            en = cm.enr_connector
            lines.append(f"**Connectors (Enriched):**  "
                         f"P={_fmt(en.precision)} R={_fmt(en.recall)} F1={_fmt(en.f1)} "
                         f"(TP={en.tp} FP={en.fp} FN={en.fn})")

        fpc = cm.fp_connectivity
        lines.append(f"**Connectivity (First Pass):** "
                     f"MatchConn F1={_fmt(fpc.strict_f1)} "
                     f"(TP={fpc.strict_tp} FP={fpc.strict_fp} FN={fpc.strict_fn}) | "
                     f"MatchName F1={_fmt(fpc.loose_f1)} (deprecated) "
                     f"(TP={fpc.loose_tp} FP={fpc.loose_fp} FN={fpc.loose_fn})")
        if cm.enr_connectivity:
            enc = cm.enr_connectivity
            lines.append(f"**Connectivity (Enriched):**  "
                         f"MatchConn F1={_fmt(enc.strict_f1)} "
                         f"(TP={enc.strict_tp} FP={enc.strict_fp} FN={enc.strict_fn}) | "
                         f"MatchName F1={_fmt(enc.loose_f1)} (deprecated) "
                         f"(TP={enc.loose_tp} FP={enc.loose_fp} FN={enc.loose_fn})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON serialiser
# ---------------------------------------------------------------------------

def _safe_asdict(obj) -> dict:
    """Convert dataclass to dict, replacing nan with null."""
    d = asdict(obj)
    def _fix(v):
        if isinstance(v, float) and math.isnan(v):
            return None
        if isinstance(v, dict):
            return {k: _fix(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [_fix(i) for i in v]
        return v
    return {k: _fix(v) for k, v in d.items()}


def build_json_report(cases: List[CaseMetrics]) -> str:
    data = {
        "generated_at": datetime.now().isoformat(),
        "case_count": len(cases),
        "cases": [_safe_asdict(cm) for cm in cases],
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_reports(cases: List[CaseMetrics], output_dir: Path):
    """Write report.md and report.json to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md = build_markdown_report(cases)
    js = build_json_report(cases)
    (output_dir / "report.md").write_text(md)
    (output_dir / "report.json").write_text(js)
    return md
