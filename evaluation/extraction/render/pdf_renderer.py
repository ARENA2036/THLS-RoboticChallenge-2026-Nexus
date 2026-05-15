"""
Renders a WireHarness CDM to a single-page A4 landscape PDF.

Layout:
  - Full page: schematic — connector boxes stacked vertically LEFT and RIGHT,
               wires routed horizontally through a channel between columns.

Column assignment algorithm:
  - Build undirected connector adjacency graph.
  - BFS 2-color to maximise cross-edges (greedy MAX-CUT approximation).
  - Conflicts (non-bipartite nodes) keep their BFS color; resulting same-side
    edges are routed as U-shapes through the outer margin.

Pin placement:
  - LEFT connectors:  pins on the RIGHT edge of the box, labels inside box.
  - RIGHT connectors: pins on the LEFT  edge of the box, labels inside box.

Wire routing (all orthogonal, no diagonal lines):
  - Cross-edge (L→R): pin → stub → vertical in LEFT half of channel →
                      horizontal bus at a per-wire mid Y →
                      vertical in RIGHT half of channel → stub → pin.
                      Every cross wire gets its own lane on each side and
                      its own bus Y so no two wires share any segment.
  - Same-side edge:   pin → stub → vertical in outer margin → stub → pin.

Requires: reportlab
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import (
    WireHarness, ConnectorOccurrence, WireOccurrence,
    CoreOccurrence, SpecialWireOccurrence, Cavity,
)

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib import colors as rl_colors
    from reportlab.pdfbase.pdfmetrics import stringWidth
except ImportError as exc:
    raise ImportError("reportlab is required: pip install reportlab") from exc

from eval.config import (
    PDF_PAGE_WIDTH_PT, PDF_PAGE_HEIGHT_PT,
    PDF_SCHEMATIC_RATIO, PDF_TABLE_RATIO,
    get_rgb,
    get_cover_colors,
    get_wire_number,
)

# ---------------------------------------------------------------------------
# Drawing constants
# ---------------------------------------------------------------------------
BOX_HEADER_H  = 24.0   # pts reserved at top of connector box for label
PIN_RADIUS    =  3.5   # filled dot radius
MIN_PIN_STEP  = 11.0   # minimum vertical pt between pin centres (prevents overlap)
WIRE_LINE_W   =  1.4
STUB_LEN      = 12.0   # horizontal stub length from pin to routing channel edge

FONT_LABEL = ("Helvetica-Bold", 7)
FONT_PART  = ("Helvetica", 5.5)
FONT_PIN   = ("Helvetica", 5)

MARGIN       = 18.0   # page margin
COL_W        = 160.0  # connector box width
BOX_GAP_V    = 10.0   # vertical gap between connector boxes in the same column
TARGET_PITCH =  7.0   # preferred horizontal spacing between adjacent routing lanes
MIN_PITCH    =  2.5   # lower bound for dense harnesses
CHAN_PAD     =  4.0   # inset from each channel edge before the first cross lane
CHAN_GAP     = 20.0   # minimum gap between the two cross-wire channel halves


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def build_cp_index(harness: WireHarness) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (cp_id → connector label, cp_id → cavity_number)."""
    cp_to_label: Dict[str, str] = {}
    cp_to_cavity: Dict[str, str] = {}
    for occ in harness.connector_occurrences:
        lbl = occ.label or occ.id
        for cp in occ.contact_points:
            cp_to_label[cp.id] = lbl
            cp_to_cavity[cp.id] = cp.cavity.cavity_number
    return cp_to_label, cp_to_cavity


def _build_adjacency(
    harness: WireHarness,
    cp_to_label: Dict[str, str],
) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = defaultdict(set)
    for conn in harness.connections:
        if len(conn.extremities) < 2:
            continue
        a = cp_to_label.get(conn.extremities[0].contact_point.id)
        b = cp_to_label.get(conn.extremities[1].contact_point.id)
        if a and b and a != b:
            adj[a].add(b)
            adj[b].add(a)
    for occ in harness.connector_occurrences:
        lbl = occ.label or occ.id
        if lbl not in adj:
            adj[lbl] = set()
    return dict(adj)


# ---------------------------------------------------------------------------
# Greedy max-cut 2-coloring
# ---------------------------------------------------------------------------

def _greedy_2color(adj: Dict[str, Set[str]]) -> Dict[str, str]:
    """
    Assign each connector label to 'L' or 'R' to maximise cross-edges (≈ MAX-CUT).

    Phase 1 — BFS 2-coloring per connected component.
      For bipartite graphs this is already optimal (all edges cross).
      For non-bipartite graphs (odd cycles, cliques) BFS may produce a very
      unbalanced partition (e.g. 1L / 4R for K5).

    Phase 2 — local-search improvement.
      Repeatedly flip any node where same_side_neighbors > cross_neighbors
      (i.e. flipping it strictly increases total cross-edges).  Repeat until
      stable.  For a star graph no flip is beneficial (each leaf has exactly
      one cross-edge to the hub), so the 1/N split is kept — that IS the
      optimal layout for a star.  For K5 this finds the balanced 2/3 split.
    """
    color: Dict[str, str] = {}

    # Phase 1: BFS per connected component
    for start in sorted(adj.keys()):
        if start in color:
            continue
        color[start] = 'L'
        queue = [start]
        while queue:
            node = queue.pop(0)
            for nb in sorted(adj[node]):
                if nb not in color:
                    color[nb] = 'R' if color[node] == 'L' else 'L'
                    queue.append(nb)

    # Phase 2: local-search MAX-CUT improvement
    improved = True
    while improved:
        improved = False
        for lbl in sorted(adj.keys()):
            same  = sum(1 for nb in adj[lbl] if color[nb] == color[lbl])
            cross = len(adj[lbl]) - same
            if same > cross:          # flipping gains (same-cross) > 0 cross-edges
                color[lbl] = 'R' if color[lbl] == 'L' else 'L'
                improved = True

    return color


def _assign_columns(
    harness: WireHarness,
    cp_to_label: Dict[str, str],
) -> Tuple[List[ConnectorOccurrence], List[ConnectorOccurrence], Dict[str, str]]:
    """Return (left_occs, right_occs, label→side) sorted alphabetically."""
    adj = _build_adjacency(harness, cp_to_label)
    color_map = _greedy_2color(adj)

    left_occs:  List[ConnectorOccurrence] = []
    right_occs: List[ConnectorOccurrence] = []
    for occ in harness.connector_occurrences:
        lbl = occ.label or occ.id
        if color_map.get(lbl, 'L') == 'L':
            left_occs.append(occ)
        else:
            right_occs.append(occ)

    left_occs.sort(key=lambda o: (o.label or o.id).lower())
    right_occs.sort(key=lambda o: (o.label or o.id).lower())
    return left_occs, right_occs, color_map


# ---------------------------------------------------------------------------
# Connector box drawing
# ---------------------------------------------------------------------------

def _compute_box_height(n_pins: int) -> float:
    """Minimum box height to comfortably fit n_pins plus the header."""
    pin_spacing = max(14.0, PIN_RADIUS * 2 + 6.0)
    return BOX_HEADER_H + 8.0 + max(n_pins, 1) * pin_spacing


def _all_cavities(occ: ConnectorOccurrence) -> List[Cavity]:
    """Full cavity list for the occurrence: prefer occurrence-level slots
    (which may carry instance overrides), fall back to the connector
    definition.  Returns cavities in slot/cavity declaration order."""
    slots = occ.slots if occ.slots else (occ.connector.slots if occ.connector else [])
    out: List[Cavity] = []
    for slot in slots:
        out.extend(slot.cavities)
    return out


def _draw_connector_box(
    c: rl_canvas.Canvas,
    occ: ConnectorOccurrence,
    bx: float, by: float, bw: float, bh: float,
    side: str,  # 'L' or 'R'
) -> Dict[str, Tuple[float, float]]:
    """
    Draw connector box.  Returns {cavity_number_str: (pin_cx, pin_cy)}.
    For side='L', pins are on the RIGHT edge (bx+bw).
    For side='R', pins are on the LEFT  edge (bx).
    """
    # Box fill & border
    c.setFillColorRGB(0.96, 0.96, 0.97)
    c.setStrokeColorRGB(0.25, 0.25, 0.25)
    c.setLineWidth(0.8)
    c.rect(bx, by, bw, bh, fill=1, stroke=1)

    # Header divider
    hdr_bottom = by + bh - BOX_HEADER_H
    c.setStrokeColorRGB(0.55, 0.55, 0.55)
    c.setLineWidth(0.4)
    c.line(bx, hdr_bottom, bx + bw, hdr_bottom)

    # Header: left half = connector label, right half = part number
    # A vertical divider separates the two halves.
    half_w = bw / 2.0
    mid_x  = bx + half_w
    c.setLineWidth(0.3)
    c.line(mid_x, hdr_bottom, mid_x, by + bh)

    label = (occ.label or occ.id)
    part  = (occ.connector.part_number if occ.connector and occ.connector.part_number else "")

    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont(*FONT_LABEL)
    c.drawString(bx + 3, hdr_bottom + 8, label[:16])
    c.setFont(*FONT_PART)
    c.drawString(mid_x + 3, hdr_bottom + 8, part[:16])

    # Pins: one per cavity in the connector definition.  Wired cavities draw
    # as filled dots, unused cavities as open circles so the connector's full
    # pinout is visible.
    cavities = _all_cavities(occ)
    used_cav_nums = {cp.cavity.cavity_number for cp in occ.contact_points}
    n_pins = len(cavities) or len(occ.contact_points)
    if n_pins == 0:
        return {}

    pin_area_top    = hdr_bottom - 4.0
    pin_area_bottom = by + 4.0
    pin_area_h      = pin_area_top - pin_area_bottom
    step = pin_area_h / (n_pins + 1)

    pin_x = bx + bw / 2.0

    # Iterate the full cavity list when available; otherwise fall back to the
    # populated contact points (preserves behavior for harnesses where the
    # connector definition doesn't enumerate cavities).
    iter_items: List[Tuple[str, bool]] = (
        [(cav.cavity_number, cav.cavity_number in used_cav_nums) for cav in cavities]
        if cavities
        else [(cp.cavity.cavity_number, True) for cp in occ.contact_points]
    )

    cav_pos: Dict[str, Tuple[float, float]] = {}
    for i, (cav_num, is_used) in enumerate(iter_items):
        py = pin_area_top - step * (i + 1)

        if is_used:
            c.setFillColorRGB(0.10, 0.10, 0.10)
            c.setStrokeColorRGB(0.10, 0.10, 0.10)
            c.circle(pin_x, py, PIN_RADIUS, fill=1, stroke=0)
        else:
            # Open circle for unused cavity
            c.setStrokeColorRGB(0.55, 0.55, 0.55)
            c.setLineWidth(0.6)
            c.circle(pin_x, py, PIN_RADIUS, fill=0, stroke=1)

        c.setFillColorRGB(0.0, 0.0, 0.0) if is_used else c.setFillColorRGB(0.45, 0.45, 0.45)
        c.setFont(*FONT_PIN)
        c.drawString(pin_x + PIN_RADIUS + 2, py - 2, str(cav_num))

        cav_pos[cav_num] = (pin_x, py)

    return cav_pos


# ---------------------------------------------------------------------------
# Wire routing
# ---------------------------------------------------------------------------

_LABEL_FONT = "Helvetica"
_LABEL_SIZE = 4.5


def _draw_wire_label(
    c: rl_canvas.Canvas,
    x: float, y: float,
    text: str,
    vertical: bool,
):
    """Draw a wire label centered at (x, y) with a white background that
    interrupts the wire passing through.  If vertical=True, the text is
    rotated 90° CCW so it reads bottom-to-top along a vertical wire."""
    if not text or text == "??":
        return
    w = stringWidth(text, _LABEL_FONT, _LABEL_SIZE)
    pad = 0.5
    baseline_drop = _LABEL_SIZE * 0.35  # approx visual vertical centering

    c.setFillColorRGB(1.0, 1.0, 1.0)
    if vertical:
        # After rotation, the text occupies (_LABEL_SIZE wide × w tall).
        c.rect(x - _LABEL_SIZE / 2 - pad, y - w / 2 - pad,
               _LABEL_SIZE + 2 * pad, w + 2 * pad, fill=1, stroke=0)
    else:
        c.rect(x - w / 2 - pad, y - _LABEL_SIZE / 2 - pad,
               w + 2 * pad, _LABEL_SIZE + 2 * pad, fill=1, stroke=0)

    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont(_LABEL_FONT, _LABEL_SIZE)
    if vertical:
        c.saveState()
        c.translate(x, y)
        c.rotate(90)
        c.drawCentredString(0, -baseline_drop, text)
        c.restoreState()
    else:
        c.drawCentredString(x, y - baseline_drop, text)


def _draw_cross_wire(
    c: rl_canvas.Canvas,
    lx: float, ly: float,   # left pin (exits rightward)
    rx: float, ry: float,   # right pin (enters from left)
    lane_L_x: float,         # per-wire vertical lane in the LEFT half of channel
    lane_R_x: float,         # per-wire vertical lane in the RIGHT half of channel
    mid_y: float,            # per-wire horizontal bus Y between the two lanes
    r: float, g: float, b: float,
    label_text: str,
):
    """Route a L→R wire as 5 orthogonal segments — short stub at each pin,
    verticals into per-wire lanes near each column, and a horizontal bus at a
    unique mid_y so no two wires share any segment across the channel."""
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(WIRE_LINE_W)

    path = c.beginPath()
    path.moveTo(lx, ly)
    path.lineTo(lane_L_x, ly)
    path.lineTo(lane_L_x, mid_y)
    path.lineTo(lane_R_x, mid_y)
    path.lineTo(lane_R_x, ry)
    path.lineTo(rx, ry)
    c.drawPath(path, stroke=1, fill=0)

    # Label on the horizontal bus (unique Y per wire), interrupting the wire.
    label_x = (lane_L_x + lane_R_x) / 2
    _draw_wire_label(c, label_x, mid_y, label_text, vertical=False)


def _draw_same_side_wire(
    c: rl_canvas.Canvas,
    ax: float, ay: float,
    bx: float, by: float,
    lane_x: float,   # vertical routing lane x in the OUTER margin of the column
    r: float, g: float, b: float,
    label_text: str,
):
    """
    Route a same-side (L-L or R-R) wire as a U-shape through the outer margin
    of its column.  Wire exits away from the channel, bends at lane_x, and
    returns.  Drawn solid.  Label is rotated 90° so it reads along the
    vertical lane, interrupting the wire where it sits.
    """
    c.setStrokeColorRGB(r, g, b)
    c.setLineWidth(WIRE_LINE_W * 0.8)

    path = c.beginPath()
    path.moveTo(ax, ay)
    path.lineTo(lane_x, ay)
    path.lineTo(lane_x, by)
    path.lineTo(bx, by)
    c.drawPath(path, stroke=1, fill=0)

    mid_y = (ay + by) / 2
    _draw_wire_label(c, lane_x, mid_y, label_text, vertical=True)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_harness_to_pdf(harness: WireHarness, output_path: Path) -> Path:
    """
    Render WireHarness CDM to a single-page A4 landscape PDF.

    Returns output_path for chaining.
    """
    W = float(PDF_PAGE_WIDTH_PT)
    H = float(PDF_PAGE_HEIGHT_PT)

    c = rl_canvas.Canvas(str(output_path), pagesize=(W, H))

    # ------------------------------------------------------------------
    # Indices and column assignment
    # ------------------------------------------------------------------
    cp_to_label, cp_to_cavity = build_cp_index(harness)
    left_occs, right_occs, color_map = _assign_columns(harness, cp_to_label)

    # Cheap pre-count pass used only for page geometry.  This mirrors the
    # later positioned classification loop, but does not need pin lookups.
    n_cross = 0
    n_same_L = 0
    n_same_R = 0
    for conn in harness.connections:
        if len(conn.extremities) < 2:
            continue
        cp0 = conn.extremities[0].contact_point.id
        cp1 = conn.extremities[1].contact_point.id
        la = cp_to_label.get(cp0)
        lb = cp_to_label.get(cp1)
        if not la or not lb:
            continue
        ca = color_map.get(la, 'L')
        cb = color_map.get(lb, 'L')
        if ca != cb:
            n_cross += 1
        elif ca == 'L':
            n_same_L += 1
        else:
            n_same_R += 1

    # ------------------------------------------------------------------
    # Layout geometry — full page is the schematic
    # ------------------------------------------------------------------
    schema_top = H
    schema_h   = H

    # Solve a single lane pitch shared by cross-channel and same-side wires.
    n_lane_slots = n_same_L + n_same_R + 2 * max(n_cross - 1, 0)
    avail = W - 2 * MARGIN - 2 * COL_W - 2 * CHAN_PAD - CHAN_GAP
    pitch = min(TARGET_PITCH, avail / max(n_lane_slots + 2, 1))
    pitch = max(pitch, MIN_PITCH)

    outer_L_W = (n_same_L + 1) * pitch
    outer_R_W = (n_same_R + 1) * pitch

    # Column boxes slide inward/outward based on the solved outer margins.
    left_box_x  = MARGIN + outer_L_W
    right_box_x = W - MARGIN - outer_R_W - COL_W

    # Routing channel: between right edge of left column and left edge of right column
    chan_left_x  = left_box_x + COL_W         # start of channel
    chan_right_x = right_box_x               # end of channel
    chan_mid_x   = (chan_left_x + chan_right_x) / 2  # default lane

    # Compute per-connector box heights driven by pin count.
    # Each box is tall enough so pins never overlap (MIN_PIN_STEP per pin).
    # If the column's total needed height exceeds the available space,
    # scale all heights down uniformly (may compress, but no overlap at scale ≥ 1).
    avail_h = schema_h - MARGIN * 2

    def _needed_h(occ: ConnectorOccurrence) -> float:
        # Box must fit ALL cavities (used and unused) so the full pinout is
        # visible — not just the wired ones.
        n = max(len(_all_cavities(occ)), len(occ.contact_points), 1)
        return BOX_HEADER_H + 8.0 + n * MIN_PIN_STEP

    def _col_heights(occs: List[ConnectorOccurrence]) -> List[float]:
        if not occs:
            return []
        raw = [_needed_h(o) for o in occs]
        total = sum(raw) + BOX_GAP_V * (len(occs) - 1)
        if total <= avail_h:
            return raw
        # Scale down to fit while keeping proportions
        scale = (avail_h - BOX_GAP_V * (len(occs) - 1)) / sum(raw)
        return [h * scale for h in raw]

    left_bhs  = _col_heights(left_occs)
    right_bhs = _col_heights(right_occs)

    def _col_y(idx: int, bhs: List[float]) -> float:
        """Bottom y of the idx-th box, stacking top-to-bottom."""
        y = schema_top - MARGIN
        for i in range(idx + 1):
            y -= bhs[i]
            if i < idx:
                y -= BOX_GAP_V
        return y

    # ------------------------------------------------------------------
    # Schematic background (full page)
    # ------------------------------------------------------------------
    c.setFillColorRGB(1.0, 1.0, 1.0)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # ------------------------------------------------------------------
    # Draw connector boxes, collect pin positions
    # ------------------------------------------------------------------
    label_to_cav: Dict[str, Dict[str, Tuple[float, float]]] = {}

    for idx, occ in enumerate(left_occs):
        bh = left_bhs[idx]
        by = _col_y(idx, left_bhs)
        cav_pos = _draw_connector_box(c, occ, left_box_x, by, COL_W, bh, side='L')
        label_to_cav[occ.label or occ.id] = cav_pos

    for idx, occ in enumerate(right_occs):
        bh = right_bhs[idx]
        by = _col_y(idx, right_bhs)
        cav_pos = _draw_connector_box(c, occ, right_box_x, by, COL_W, bh, side='R')
        label_to_cav[occ.label or occ.id] = cav_pos

    # ------------------------------------------------------------------
    # Draw wires
    # ------------------------------------------------------------------
    # First pass: classify every drawable connection as cross or same-side
    # and resolve pin positions.  We need the total count of cross-connections
    # before we can assign evenly-spaced lanes.
    ConnRec = Tuple  # (x_a, y_a, x_b, y_b, iec_code, r, g, b, side_a)
    cross_recs:     List = []
    same_recs_L:    List = []
    same_recs_R:    List = []

    # CoreOccurrence connections need the parent SpecialWireOccurrence to
    # resolve the orderable cable's part_number — the core itself has none.
    core_to_swo_wire: Dict[str, str] = {}
    for swo in harness.special_wire_occurrences:
        pn = swo.wire.part_number if swo.wire and swo.wire.part_number else ""
        if pn:
            for co in swo.core_occurrences:
                core_to_swo_wire[co.id] = pn

    for conn in harness.connections:
        if len(conn.extremities) < 2:
            continue
        cp0 = conn.extremities[0].contact_point.id
        cp1 = conn.extremities[1].contact_point.id
        la = cp_to_label.get(cp0)
        lb = cp_to_label.get(cp1)
        if not la or not lb:
            continue
        cav_a = cp_to_cavity.get(cp0, "1")
        cav_b = cp_to_cavity.get(cp1, "1")
        pos_a = label_to_cav.get(la, {}).get(cav_a)
        pos_b = label_to_cav.get(lb, {}).get(cav_b)
        if not pos_a or not pos_b:
            continue

        iec_code = "??"
        display_label = "??"
        if conn.wire_occurrence:
            cols = get_cover_colors(conn.wire_occurrence)
            if cols:
                iec_code = cols[0].color_code.upper()
                
            wire_obj = getattr(conn.wire_occurrence, "wire", None)
            if wire_obj and getattr(wire_obj, "part_number", None):
                display_label = wire_obj.part_number
            elif getattr(conn.wire_occurrence, "core", None):
                # CoreOccurrence: prefer the parent cable's part_number.
                swo_pn = core_to_swo_wire.get(conn.wire_occurrence.id, "")
                if swo_pn:
                    display_label = swo_pn
                else:
                    core_obj = conn.wire_occurrence.core
                    display_label = getattr(core_obj, "cable_designator", "") or getattr(core_obj, "wire_type", "")
                
            if not display_label or display_label == "??":
                display_label = get_wire_number(conn.wire_occurrence)
                
            if not display_label:
                display_label = iec_code
                
        r, g, b = get_rgb(iec_code)

        ca = color_map.get(la, 'L')
        cb = color_map.get(lb, 'L')
        x_a, y_a = pos_a
        x_b, y_b = pos_b

        if ca != cb:
            # Normalise so "a" is always the LEFT pin
            if ca == 'L':
                cross_recs.append((x_a, y_a, x_b, y_b, display_label, r, g, b))
            else:
                cross_recs.append((x_b, y_b, x_a, y_a, display_label, r, g, b))
        elif ca == 'L':
            same_recs_L.append((x_a, y_a, x_b, y_b, display_label, r, g, b))
        else:
            same_recs_R.append((x_a, y_a, x_b, y_b, display_label, r, g, b))

    # Channel geometry.
    # Cross-edge wires use 5-segment routing: every wire gets its own vertical
    # lane in each half of the channel AND its own horizontal bus Y between
    # them, so no two wires share any segment across the channel.
    # Same-side wires route in the OUTER margin of their column — L-L wires
    # to the left of the left column, R-R wires to the right of the right
    # column — so they never collide with cross wires.
    n_cross = len(cross_recs)

    # Sort cross wires by average pin Y (top first) so the vertical bus-Y
    # assignment roughly follows pin positions and keeps verticals short.
    cross_recs.sort(key=lambda rec: -(rec[1] + rec[3]) / 2)

    cross_span = max(n_cross - 1, 0) * pitch
    L_zone_lo = chan_left_x  + CHAN_PAD
    L_zone_hi = L_zone_lo + cross_span
    R_zone_hi = chan_right_x - CHAN_PAD
    R_zone_lo = R_zone_hi - cross_span

    # Mid-Y bus spans the vertical extent of the actually-drawn pins (boxes
    # stack from the top so unused vertical space sits at the bottom of the
    # page — routing there would produce huge pointless verticals).
    pin_ys = [y for cav_pos in label_to_cav.values() for (_, y) in cav_pos.values()]
    if pin_ys:
        mid_top = max(pin_ys) + 6.0
        mid_bot = min(pin_ys) - 6.0
    else:
        mid_top = schema_top - MARGIN - 8.0
        mid_bot = MARGIN + 8.0

    def _cross_lane_L(i: int) -> float:
        return L_zone_lo + i * pitch

    def _cross_lane_R(i: int) -> float:
        return R_zone_lo + i * pitch

    def _cross_mid_y(i: int) -> float:
        # Descending: i=0 gets the top bus line, last wire gets the bottom.
        if n_cross <= 1:
            return mid_top
        return mid_top + (mid_bot - mid_top) * i / (n_cross - 1)

    def _same_lane_L(i: int) -> float:
        # Lanes in the LEFT outer margin, stepping further out for each wire.
        return left_box_x - (i + 1) * pitch

    def _same_lane_R(i: int) -> float:
        # Lanes in the RIGHT outer margin, stepping further out for each wire.
        return right_box_x + COL_W + (i + 1) * pitch

    # Draw cross-edge wires (each gets its own lane_L, lane_R, and mid_y)
    for i, (lx, ly, rx, ry, label_text, r, g, b) in enumerate(cross_recs):
        _draw_cross_wire(
            c, lx, ly, rx, ry,
            _cross_lane_L(i), _cross_lane_R(i), _cross_mid_y(i),
            r, g, b, label_text,
        )

    # Draw same-side wires (solid U-shapes in the outer margin of each column)
    for i, (x_a, y_a, x_b, y_b, label_text, r, g, b) in enumerate(same_recs_L):
        _draw_same_side_wire(
            c, x_a, y_a, x_b, y_b, _same_lane_L(i), r, g, b, label_text,
        )

    for i, (x_a, y_a, x_b, y_b, label_text, r, g, b) in enumerate(same_recs_R):
        _draw_same_side_wire(
            c, x_a, y_a, x_b, y_b, _same_lane_R(i), r, g, b, label_text,
        )

    # ------------------------------------------------------------------
    # Title block (bottom-right corner)
    # ------------------------------------------------------------------
    c.setFont("Helvetica-Bold", 6)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    pn  = harness.part_number or ""
    ver = harness.version or ""
    co  = harness.company_name or ""
    c.drawString(W * 0.55, 6, f"Nr: {pn}   Rev: {ver}   Firma: {co}")

    c.save()
    return output_path


# ---------------------------------------------------------------------------
# Bill of Materials
# ---------------------------------------------------------------------------

def write_bom(harness: WireHarness, output_path: Path) -> Path:
    """
    Write a semicolon-separated BOM alongside the PDF.

    Columns: row_nr; type; part_name; part_number; unit; value

    Rows:
      - One row per connector occurrence (unit = amount, value = 1)
      - One aggregated row per unique wire part number (unit = mm, value = total length)
      - One row per unique terminal part number (unit = amount, value = count)
    """
    from collections import defaultdict

    rows: List[Dict] = []

    # One row per connector occurrence
    for occ in harness.connector_occurrences:
        pn = (occ.connector.part_number if occ.connector and occ.connector.part_number
              else "—")
        rows.append(dict(
            type="connector",
            part_name=occ.label or occ.id,
            part_number=pn,
            unit="amount",
            value=1,
        ))

    # Map each CoreOccurrence back to its parent SpecialWireOccurrence so we
    # can recover the orderable cable's part_number when a connection carries
    # a core (multi-core cable branch of the wire_occurrence union).
    core_to_swo: Dict[str, SpecialWireOccurrence] = {}
    for swo in harness.special_wire_occurrences:
        for co in swo.core_occurrences:
            core_to_swo[co.id] = swo

    # One row per schematic wire — i.e. per connection's wire_occurrence,
    # deduped by id so a wire shared across connections collapses to one row.
    seen_ids: Set[str] = set()
    wire_rows: List[Dict] = []

    def _add_wire_occurrence(wo: WireOccurrence):
        pn     = wo.wire.part_number if wo.wire and wo.wire.part_number else wo.id
        name   = wo.wire_number or wo.id
        length = (
            wo.length_production
            or wo.length_dmu
            or (wo.length.length_mm if wo.length else 0.0)
            or 0.0
        )
        wire_rows.append(dict(
            type="wire", part_name=name, part_number=pn,
            unit="mm", value=round(length, 1),
        ))

    def _add_core_occurrence(co: CoreOccurrence):
        swo = core_to_swo.get(co.id)
        pn = (swo.wire.part_number if swo and swo.wire and swo.wire.part_number
              else (co.core.cable_designator if co.core and co.core.cable_designator
                    else co.id))
        name   = co.wire_number or co.id
        length = (co.length.length_mm if co.length else 0.0) or 0.0
        wire_rows.append(dict(
            type="wire", part_name=name, part_number=pn,
            unit="mm", value=round(length, 1),
        ))

    for conn in harness.connections:
        wo = conn.wire_occurrence
        if not wo or wo.id in seen_ids:
            continue
        seen_ids.add(wo.id)
        if isinstance(wo, WireOccurrence):
            _add_wire_occurrence(wo)
        elif isinstance(wo, CoreOccurrence):
            _add_core_occurrence(wo)

    # Also surface wires from the top-level lists that aren't on any connection.
    for wo in harness.wire_occurrences:
        if wo.id not in seen_ids:
            seen_ids.add(wo.id)
            _add_wire_occurrence(wo)
    for swo in harness.special_wire_occurrences:
        for co in swo.core_occurrences:
            if co.id not in seen_ids:
                seen_ids.add(co.id)
                _add_core_occurrence(co)

    rows.extend(wire_rows)

    bom_path = output_path.with_suffix(".csv")
    with bom_path.open("w", encoding="utf-8") as f:
        f.write("row_nr;type;part_name;part_number;unit;value\n")
        for i, row in enumerate(rows, 1):
            f.write(f"{i};{row['type']};{row['part_name']};"
                    f"{row['part_number']};{row['unit']};{row['value']}\n")

    return bom_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Render WireHarness JSON files to PDF schematics."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing harness_*.json files.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output directory for PDFs (default: <input_dir>/pdfs).",
    )
    args = parser.parse_args()

    input_dir: Path = args.input_dir.resolve()
    output_dir: Path = (args.output_dir or input_dir / "pdfs").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    from definitions.cdm_schema import WireHarness

    files = sorted(input_dir.glob("*.json"))
    if not files:
        print(f"No JSON files found in {input_dir}")
        raise SystemExit(1)

    ok = errors = 0
    for f in files:
        out = output_dir / f.with_suffix(".pdf").name
        try:
            harness = WireHarness.model_validate(json.loads(f.read_text()))
            render_harness_to_pdf(harness, out)
            write_bom(harness, out)
            print(f"  OK  {f.name} -> {out.name}, {out.with_suffix('.csv').name}")
            ok += 1
        except Exception as exc:
            print(f"  ERR {f.name}: {exc}")
            errors += 1

    print(f"\n{ok} rendered, {errors} failed -> {output_dir}")
