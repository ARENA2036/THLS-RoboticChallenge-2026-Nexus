"""
Connectivity F1 metrics.

Matches extracted wires against GT Connections by **part number**:

  - Loose:   wire part_number only (identity of the wire type).
  - Strict:  wire part_number + unordered pair of the two endpoints'
             connector part_numbers.

The prior "label + cavity" fingerprint is replaced by part-number identity,
which is what the BOM already encodes and what the user asked us to match
against. Endpoint connector part_numbers are derived from the
ConnectorOccurrence that owns each contact_point on the GT side, and from
the extracted Connector whose connector_id matches the wire's
source/destination on the pred side.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import WireHarness
from parsing.util.structure import WiringDiagram


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Strict fingerprint = (wire part_number, frozenset of the two endpoint
# connector part_numbers). Frozenset handles endpoint order.
StrictFP = Tuple[str, FrozenSet[str]]

# Loose fingerprint = wire part_number only.
LooseFP = str


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ConnectivityResult:
    strict_precision: float
    strict_recall: float
    strict_f1: float
    strict_tp: int
    strict_fp: int
    strict_fn: int

    loose_precision: float
    loose_recall: float
    loose_f1: float
    loose_tp: int
    loose_fp: int
    loose_fn: int


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def _prf_from_multisets(
    pred: Counter, gt: Counter
) -> Tuple[float, float, float, int, int, int]:
    """Precision/recall/F1 on multisets (Counter). TP = sum of min counts."""
    tp = sum((pred & gt).values())
    fp = sum(pred.values()) - tp
    fn = sum(gt.values()) - tp
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return p, r, _f1(p, r), tp, fp, fn


# ---------------------------------------------------------------------------
# GT fingerprint builder
# ---------------------------------------------------------------------------

def _cp_to_connector_part_number(harness: WireHarness) -> Dict[str, str]:
    """contact_point.id → owning connector_occurrence's connector.part_number."""
    out: Dict[str, str] = {}
    for occ in harness.connector_occurrences:
        part = occ.connector.part_number or ""
        for cp in occ.contact_points:
            out[cp.id] = part
    return out


def _wire_occurrence_part_number(wo) -> str:
    """Extract part_number from a WireOccurrence or CoreOccurrence."""
    wire = getattr(wo, "wire", None)
    if wire is not None and getattr(wire, "part_number", None):
        return wire.part_number
    core = getattr(wo, "core", None)
    if core is not None and getattr(core, "part_number", None):
        return core.part_number
    return ""


def _build_gt_fingerprints(
    harness: WireHarness,
    cp_to_cavity: Dict[str, str]
) -> Tuple[Counter, Counter]:
    """Build multisets of strict + loose fingerprints from GT."""
    cp_to_part = _cp_to_connector_part_number(harness)
    strict: Counter = Counter()
    loose: Counter = Counter()

    for conn in harness.connections:
        if len(conn.extremities) < 2 or conn.wire_occurrence is None:
            continue

        wire_part = _wire_occurrence_part_number(conn.wire_occurrence)
        if not wire_part:
            continue

        cp0 = conn.extremities[0].contact_point.id
        cp1 = conn.extremities[1].contact_point.id
        ep_a = cp_to_part.get(cp0, "")
        ep_b = cp_to_part.get(cp1, "")
        cav_a = cp_to_cavity.get(cp0, "")
        cav_b = cp_to_cavity.get(cp1, "")
        
        if not ep_a or not ep_b:
            continue

        strict[(wire_part, frozenset({f"{ep_a}:{cav_a}", f"{ep_b}:{cav_b}"}))] += 1
        loose[wire_part] += 1

    return strict, loose


# ---------------------------------------------------------------------------
# Pred fingerprint builder
# ---------------------------------------------------------------------------

def _build_pred_fingerprints(
    diagram: WiringDiagram,
) -> Tuple[Counter, Counter]:
    """Build multisets of strict + loose fingerprints from extracted diagram."""
    # connector_id → connector_name (== BOM part_number, per extractor convention).
    id_to_part: Dict[str, str] = {
        c.connector_id: (c.connector_name or "") for c in diagram.connectors
    }

    strict: Counter = Counter()
    loose: Counter = Counter()

    # Determine pin conflicts: a valid diagram can only hold ONE wire per pin.
    pin_occupancy = {}
    for w in diagram.wires:
        src_key = (w.source_connector_id, w.source_pin_number)
        dst_key = (w.destination_connector_id, w.destination_pin_number)
        if src_key[0] and src_key[1]:
            pin_occupancy[src_key] = pin_occupancy.get(src_key, 0) + 1
        if dst_key[0] and dst_key[1]:
            pin_occupancy[dst_key] = pin_occupancy.get(dst_key, 0) + 1

    for idx, w in enumerate(diagram.wires):
        src_key = (w.source_connector_id, w.source_pin_number)
        dst_key = (w.destination_connector_id, w.destination_pin_number)

        is_conflicted = False
        if src_key[0] and src_key[1] and pin_occupancy.get(src_key, 0) > 1:
            is_conflicted = True
        if dst_key[0] and dst_key[1] and pin_occupancy.get(dst_key, 0) > 1:
            is_conflicted = True

        if is_conflicted:
            # Both wires sharing a pin are physically invalid. Emit a unique
            # sentinel fingerprint per wire so it can't match any GT entry,
            # which makes it count as FP (and never as TP).
            sentinel = f"__pin_conflict__:{idx}"
            strict[(sentinel, frozenset({sentinel}))] += 1
            loose[sentinel] += 1
            continue

        wire_part = w.part_number or ""
        if not wire_part:
            continue
        ep_a = id_to_part.get(w.source_connector_id, "")
        ep_b = id_to_part.get(w.destination_connector_id, "")
        cav_a = str(w.source_pin_number) if w.source_pin_number else ""
        cav_b = str(w.destination_pin_number) if w.destination_pin_number else ""
        
        if not ep_a or not ep_b:
            # Endpoint connector part_numbers unresolved → strict impossible,
            # but loose still counts (the wire type was extracted).
            loose[wire_part] += 1
            continue

        strict[(wire_part, frozenset({f"{ep_a}:{cav_a}", f"{ep_b}:{cav_b}"}))] += 1
        loose[wire_part] += 1

    return strict, loose


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compute_connectivity_f1(
    gt_harness: WireHarness,
    pred_diagram: Optional[WiringDiagram],
    cp_to_cavity: Optional[Dict[str, str]] = None,
) -> ConnectivityResult:
    cp_to_cavity = cp_to_cavity or {}

    gt_strict, gt_loose = _build_gt_fingerprints(gt_harness, cp_to_cavity)

    if pred_diagram is None or not pred_diagram.wires:
        n_gt_s = sum(gt_strict.values())
        n_gt_l = sum(gt_loose.values())
        return ConnectivityResult(
            strict_precision=0.0, strict_recall=0.0, strict_f1=0.0,
            strict_tp=0, strict_fp=0, strict_fn=n_gt_s,
            loose_precision=0.0, loose_recall=0.0, loose_f1=0.0,
            loose_tp=0, loose_fp=0, loose_fn=n_gt_l,
        )

    pred_strict, pred_loose = _build_pred_fingerprints(pred_diagram)

    sp, sr, sf1, stp, sfp, sfn = _prf_from_multisets(pred_strict, gt_strict)
    lp, lr, lf1, ltp, lfp, lfn = _prf_from_multisets(pred_loose, gt_loose)

    return ConnectivityResult(
        strict_precision=sp, strict_recall=sr, strict_f1=sf1,
        strict_tp=stp, strict_fp=sfp, strict_fn=sfn,
        loose_precision=lp, loose_recall=lr, loose_f1=lf1,
        loose_tp=ltp, loose_fp=lfp, loose_fn=lfn,
    )
