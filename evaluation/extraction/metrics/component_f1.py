"""
Component F1 metrics.

A TP requires BOTH the connector part_number AND its pin count to match
(extracted `connector_name` == GT `connector.part_number` AND
extracted `pin_count` == len(GT `contact_points`)). Fuzzy similarity on
part_number is allowed as a fallback for minor formatting drift
("TE 6P" vs "TE-6P"), but the pin count must still match exactly.
"""

from __future__ import annotations

import difflib
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import WireHarness
from parsing.util.structure import WiringDiagram, Connector as ExtConn

from eval.config import LABEL_MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: Optional[str]) -> str:
    """Lowercase, strip, normalize separators to single space."""
    import re
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _similarity(a: Optional[str], b: Optional[str]) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ConnectorMatchResult:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_exact(
    gt_slots: List[Tuple[str, int]],
    pred_slots: List[Tuple[Optional[str], int]],
) -> List[Tuple[int, int]]:
    """Multiset matching on (normalized part_number, pin_count). Both must match."""
    pred_by_key: Dict[Tuple[str, int], List[int]] = defaultdict(list)
    for pi, (pn, pc) in enumerate(pred_slots):
        key = (_normalize(pn), pc)
        if key[0]:
            pred_by_key[key].append(pi)

    pairs: List[Tuple[int, int]] = []
    for gi, (gpn, gpc) in enumerate(gt_slots):
        key = (_normalize(gpn), gpc)
        if not key[0]:
            continue
        if pred_by_key[key]:
            pi = pred_by_key[key].pop(0)
            pairs.append((gi, pi))
    return pairs


def _fuzzy_fallback(
    gt_slots: List[Tuple[str, int]],
    pred_slots: List[Tuple[Optional[str], int]],
    used_gt: set,
    used_pred: set,
    threshold: float,
) -> List[Tuple[int, int, float]]:
    """Greedy fuzzy bipartite matching on leftover slots.

    Fuzzy on part_number; pin_count must still match exactly.
    """
    scores: List[Tuple[float, int, int]] = []
    for gi, (gpn, gpc) in enumerate(gt_slots):
        if gi in used_gt:
            continue
        for pi, (ppn, ppc) in enumerate(pred_slots):
            if pi in used_pred:
                continue
            if ppc != gpc:
                continue
            s = _similarity(gpn, ppn)
            if s >= threshold:
                scores.append((s, gi, pi))
    scores.sort(reverse=True)

    out: List[Tuple[int, int, float]] = []
    local_gt = set(used_gt)
    local_pred = set(used_pred)
    for score, gi, pi in scores:
        if gi in local_gt or pi in local_pred:
            continue
        out.append((gi, pi, score))
        local_gt.add(gi)
        local_pred.add(pi)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compute_connector_f1(
    gt_harness: WireHarness,
    pred_diagram: Optional[WiringDiagram],
    threshold: float = LABEL_MATCH_THRESHOLD,
) -> ConnectorMatchResult:
    """
    Match extracted connectors to GT connector occurrences.

    TP requires both the connector part_number AND its pin count to match.
    """
    gt_occs = gt_harness.connector_occurrences

    def _physical_pin_count(occ) -> int:
        """Physical pin count from the connector's slot/cavity structure.

        Falls back to len(contact_points) when no slots are defined.
        """
        total = sum(s.num_cavities for s in occ.connector.slots)
        return total if total > 0 else len(occ.contact_points)

    gt_slots: List[Tuple[str, int]] = [
        ((occ.connector.part_number or ""), _physical_pin_count(occ))
        for occ in gt_occs
    ]

    if pred_diagram is None or not pred_diagram.connectors:
        return ConnectorMatchResult(
            precision=0.0, recall=0.0, f1=0.0,
            tp=0, fp=0, fn=len(gt_slots),
        )

    pred_conns: List[ExtConn] = pred_diagram.connectors
    pred_slots: List[Tuple[Optional[str], int]] = [
        (pc.connector_name, pc.pin_count) for pc in pred_conns
    ]

    exact_pairs = _match_exact(gt_slots, pred_slots)
    used_gt = {gi for gi, _ in exact_pairs}
    used_pred = {pi for _, pi in exact_pairs}

    fuzzy_pairs = _fuzzy_fallback(
        gt_slots, pred_slots, used_gt, used_pred, threshold,
    )

    all_pairs: List[Tuple[int, int]] = (
        list(exact_pairs) + [(gi, pi) for gi, pi, _ in fuzzy_pairs]
    )

    tp = len(all_pairs)
    fp = len(pred_conns) - tp
    fn = len(gt_slots) - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    return ConnectorMatchResult(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        tp=tp, fp=fp, fn=fn,
    )
