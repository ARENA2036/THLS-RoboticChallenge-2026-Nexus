#!/usr/bin/env python3
"""
Generate synthetic CDM harnesses with an increasing number of pins.

One harness is produced for every even pin count from 2 to MAX_PINS (default 60).
Pins are the total number of contact points across all connectors; each wire
consumes exactly two pins (one at each end), so n_wires = total_pins // 2.

Pins are distributed *unevenly* across a random number of connectors:
  2–6  pins → 2 connectors
  8–20 pins → 2–4 connectors (random)
  22–40 pins → 3–6 connectors (random)
  42+  pins → 4–8 connectors (random)

Run from project root:
    python public/cdm/examples/generate_synthetic_harnesses.py
    python public/cdm/examples/generate_synthetic_harnesses.py --max-pins 120
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from public.cdm.definitions.cdm_schema import (
    CartesianPoint,
    Cavity,
    Connection,
    Connector,
    ContactPoint,
    Extremity,
    Node,
    Segment,
    Slot,
    Terminal,
    Wire,
    WireColor,
    WireHarness,
    WireOccurrence,
)
from layout_generator.LayoutModels import ConnectorOccurrence, Vector2D

# ── Pin-sweep configuration ───────────────────────────────────────────────────
MAX_PINS  = 60   # maximum total pins (inclusive, must be even)
N_HARNESSES = 100  # total number of harnesses to generate

# ── Workspace limits ──────────────────────────────────────────────────────────
X_MIN, X_MAX = 100.0, 1200.0
Y_MIN, Y_MAX = 100.0, 800.0
X_MID = (X_MIN + X_MAX) / 2.0  # 650 mm — natural board centre / left-right split

# ── Connector library (realistic automotive part numbers) ─────────────────────
CONNECTOR_LIBRARY = [
    ("MOLEX-3P",   "housing", 3),
    ("MOLEX-6P",   "housing", 6),
    ("MOLEX-12P",  "housing", 12),
    ("MOLEX-24P",  "housing", 24),
    ("TE-6P",      "housing", 6),
    ("TE-12P",     "housing", 12),
    ("TE-24P",     "housing", 24),
    ("DELPHI-12P", "housing", 12),
    ("DELPHI-24P", "housing", 24),
]

# ── Wire library (realistic automotive FLRY types + multi-core) ───────────────
WIRE_LIBRARY = [
    # (part_number, wire_type, cross_section, outside_diameter, color_code, weight)
    ("FLRY-0.35-RD", "wire", 0.35, 1.4, "RD", 0.70),
    ("FLRY-0.35-BK", "wire", 0.35, 1.4, "BK", 0.70),
    ("FLRY-0.5-RD",  "wire", 0.50, 1.8, "RD", 0.15),
    ("FLRY-0.5-BK",  "wire", 0.50, 1.8, "BK", 0.15),
    ("FLRY-0.5-WH",  "wire", 0.50, 1.8, "WH", 0.10),
    ("FLRY-0.5-YE",  "wire", 0.50, 1.8, "YE", 0.10),
    ("FLRY-0.5-BU",  "wire", 0.50, 1.8, "BU", 0.10),
    ("FLRY-0.5-GN",  "wire", 0.50, 1.8, "GN", 0.10),
    ("FLRY-1.0-RD",  "wire", 1.00, 2.4, "RD", 0.10),
    ("FLRY-1.0-BK",  "wire", 1.00, 2.4, "BK", 0.05),
    ("FLRY-1.5-RD",  "wire", 1.50, 2.8, "RD", 0.05),
]

# ── Mating directions ─────────────────────────────────────────────────────────
MATING_DIRECTIONS = [
    Vector2D(x=1.0,  y=0.0),   # +X
    Vector2D(x=-1.0, y=0.0),   # -X
    Vector2D(x=0.0,  y=1.0),   # +Y
    Vector2D(x=0.0,  y=-1.0),  # -Y
]

# ── Connector physical dimensions by cavity count ─────────────────────────────
def _connector_dims(n_cavities: int) -> Tuple[float, float]:
    """Return (width_mm, height_mm) for a connector with n_cavities."""
    if n_cavities <= 3:
        return (20.0, 12.0)
    elif n_cavities <= 6:
        return (28.0, 14.0)
    elif n_cavities <= 12:
        return (40.0, 18.0)
    else:
        return (55.0, 22.0)


# ── Graph utilities ───────────────────────────────────────────────────────────

def _build_graph(segments: List[Segment]) -> Dict[str, List[Tuple[str, Segment]]]:
    """Build adjacency list: node_id → [(neighbour_node_id, segment)]."""
    graph: Dict[str, List[Tuple[str, Segment]]] = defaultdict(list)
    for seg in segments:
        a, b = seg.start_node.id, seg.end_node.id
        graph[a].append((b, seg))
        graph[b].append((a, seg))
    return graph


def _find_path_segments(
    graph: Dict[str, List[Tuple[str, Segment]]],
    start: str,
    end: str,
) -> Optional[List[Segment]]:
    """BFS to find the segment path between two nodes. Returns None if unreachable."""
    if start == end:
        return []
    visited = {start}
    queue = deque([(start, [])])
    while queue:
        current, path = queue.popleft()
        for neighbour, seg in graph[current]:
            if neighbour == end:
                return path + [seg]
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append((neighbour, path + [seg]))
    return None


# ── Topology builders ─────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _build_backbone_topology(
    rng: random.Random,
    n_connectors: int,
) -> Tuple[List[Node], List[Segment], List[str]]:
    """
    One horizontal trunk with branch spokes leading to connector leaf nodes.
    Returns (nodes, segments, connector_node_ids).
    """
    nodes: List[Node] = []
    segments: List[Segment] = []

    # Number of trunk internal nodes (not connector leaves)
    n_trunk = max(2, min(n_connectors - 1, 8))

    # Space trunk nodes evenly along X, at Y=450mm
    x_step = (X_MAX - X_MIN) / (n_trunk + 1)
    trunk_nodes = []
    for i in range(n_trunk):
        nx = _clamp(X_MIN + x_step * (i + 1), X_MIN + 50, X_MAX - 50)
        ny = _clamp(450.0 + rng.uniform(-40, 40), Y_MIN + 100, Y_MAX - 100)
        node = Node(id=f"trunk_{i}", position=CartesianPoint(coord_x=nx, coord_y=ny))
        nodes.append(node)
        trunk_nodes.append(node)

    # Connect trunk nodes in a chain
    for i in range(len(trunk_nodes) - 1):
        segments.append(Segment(
            id=f"seg_trunk_{i}_{i+1}",
            start_node=trunk_nodes[i],
            end_node=trunk_nodes[i + 1],
            length=_node_dist(trunk_nodes[i], trunk_nodes[i + 1]),
        ))

    # Distribute connectors among trunk attach points
    connector_node_ids: List[str] = []
    attach_indices = _distribute(n_connectors, n_trunk)

    for leaf_idx, trunk_idx in enumerate(attach_indices):
        attach_node = trunk_nodes[trunk_idx]
        bx = attach_node.position.coord_x
        # Alternate above/below trunk
        if leaf_idx % 2 == 0:
            by = _clamp(attach_node.position.coord_y + rng.uniform(120, 250), Y_MIN + 30, Y_MAX - 30)
        else:
            by = _clamp(attach_node.position.coord_y - rng.uniform(120, 250), Y_MIN + 30, Y_MAX - 30)
        bx = _clamp(bx + rng.uniform(-60, 60), X_MIN + 30, X_MAX - 30)

        leaf = Node(id=f"conn_{leaf_idx}", position=CartesianPoint(coord_x=bx, coord_y=by))
        nodes.append(leaf)
        connector_node_ids.append(leaf.id)
        segments.append(Segment(
            id=f"seg_branch_{leaf_idx}",
            start_node=attach_node,
            end_node=leaf,
            length=_node_dist(attach_node, leaf),
        ))

    return nodes, segments, connector_node_ids


def _build_tree_topology(
    rng: random.Random,
    n_connectors: int,
) -> Tuple[List[Node], List[Segment], List[str]]:
    """
    Recursive binary/trinary tree. Root is an internal node, leaves are connectors.
    """
    nodes: List[Node] = []
    segments: List[Segment] = []
    connector_node_ids: List[str] = []

    root = Node(id="root", position=CartesianPoint(coord_x=X_MID, coord_y=450.0))
    nodes.append(root)

    # Build leaf list by iterative branching
    frontier = [(root, 0)]   # (node, depth)
    leaf_count = 0
    branch_factor = 3 if n_connectors > 10 else 2

    while leaf_count < n_connectors:
        remaining = n_connectors - leaf_count
        if not frontier:
            break
        parent, depth = frontier.pop(0)
        px, py = parent.position.coord_x, parent.position.coord_y

        n_children = min(branch_factor, remaining)
        if n_children < 1:
            break

        step_x = rng.uniform(150, 280)
        step_y = rng.uniform(100, 220)
        offsets = _branch_offsets(n_children, step_x, step_y)

        for k, (dx, dy) in enumerate(offsets):
            if leaf_count >= n_connectors:
                break
            cx = _clamp(px + dx, X_MIN + 30, X_MAX - 30)
            cy = _clamp(py + dy * (-1 if rng.random() < 0.5 else 1), Y_MIN + 30, Y_MAX - 30)
            child_id = f"conn_{leaf_count}"
            child = Node(id=child_id, position=CartesianPoint(coord_x=cx, coord_y=cy))
            nodes.append(child)
            segments.append(Segment(
                id=f"seg_{parent.id}_{child_id}",
                start_node=parent,
                end_node=child,
                length=_node_dist(parent, child),
            ))
            connector_node_ids.append(child_id)
            leaf_count += 1
            # Only expand node further if depth < max and children still needed
            if depth < 3 and leaf_count < n_connectors:
                frontier.append((child, depth + 1))

    return nodes, segments, connector_node_ids


def _build_star_topology(
    rng: random.Random,
    n_connectors: int,
) -> Tuple[List[Node], List[Segment], List[str]]:
    """
    Central hub node, N spokes each ending at a connector leaf.
    Hub is placed at board centre so both arms share the load.
    """
    nodes: List[Node] = []
    segments: List[Segment] = []
    connector_node_ids: List[str] = []

    hub = Node(id="hub", position=CartesianPoint(coord_x=X_MID, coord_y=450.0))
    nodes.append(hub)

    angle_step = 2 * math.pi / n_connectors
    for i in range(n_connectors):
        angle = angle_step * i
        spoke_len = rng.uniform(150, 400)
        # Scale spoke to fit within board
        cx = _clamp(X_MID + spoke_len * math.cos(angle), X_MIN + 30, X_MAX - 30)
        cy = _clamp(450.0 + spoke_len * math.sin(angle), Y_MIN + 30, Y_MAX - 30)
        leaf = Node(id=f"conn_{i}", position=CartesianPoint(coord_x=cx, coord_y=cy))
        nodes.append(leaf)
        connector_node_ids.append(leaf.id)
        segments.append(Segment(
            id=f"seg_spoke_{i}",
            start_node=hub,
            end_node=leaf,
            length=_node_dist(hub, leaf),
        ))

    return nodes, segments, connector_node_ids


def _build_linear_topology(
    rng: random.Random,
    n_connectors: int,
) -> Tuple[List[Node], List[Segment], List[str]]:
    """
    Simple chain: connectors placed left-to-right in a zigzag.
    """
    nodes: List[Node] = []
    segments: List[Segment] = []
    connector_node_ids: List[str] = []

    x_step = (X_MAX - X_MIN - 100) / max(n_connectors - 1, 1)
    for i in range(n_connectors):
        nx = _clamp(X_MIN + 50 + x_step * i, X_MIN + 30, X_MAX - 30)
        ny = 450.0 if i % 2 == 0 else _clamp(450.0 + rng.choice([-1, 1]) * rng.uniform(80, 180), Y_MIN + 30, Y_MAX - 30)
        node = Node(id=f"conn_{i}", position=CartesianPoint(coord_x=nx, coord_y=ny))
        nodes.append(node)
        connector_node_ids.append(node.id)
        if i > 0:
            segments.append(Segment(
                id=f"seg_{i-1}_{i}",
                start_node=nodes[i - 1],
                end_node=node,
                length=_node_dist(nodes[i - 1], node),
            ))

    return nodes, segments, connector_node_ids


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node_dist(a: Node, b: Node) -> float:
    return math.sqrt(
        (a.position.coord_x - b.position.coord_x) ** 2
        + (a.position.coord_y - b.position.coord_y) ** 2
    )


def _distribute(n_items: int, n_buckets: int) -> List[int]:
    """Distribute n_items into n_buckets as evenly as possible (returns bucket index per item)."""
    base = n_items // n_buckets
    extra = n_items % n_buckets
    counts = [base + (1 if i < extra else 0) for i in range(n_buckets)]
    result = []
    for idx, count in enumerate(counts):
        result.extend([idx] * count)
    return result


def _branch_offsets(n: int, step_x: float, step_y: float) -> List[Tuple[float, float]]:
    """Return (dx, dy) offsets for n children, spread left/right/down."""
    if n == 1:
        return [(0, step_y)]
    elif n == 2:
        return [(-step_x * 0.6, step_y * 0.8), (step_x * 0.6, step_y * 0.8)]
    else:
        return [
            (-step_x, step_y * 0.5),
            (0, step_y),
            (step_x, step_y * 0.5),
        ]


def _pick_connector_def(rng: random.Random, min_cavities: int) -> Tuple[str, str, int]:
    """Pick a connector from the library with at least min_cavities."""
    candidates = [(pn, ct, nc) for pn, ct, nc in CONNECTOR_LIBRARY if nc >= min_cavities]
    if not candidates:
        candidates = [CONNECTOR_LIBRARY[-1]]  # largest available
    return rng.choice(candidates)


def _pick_wire_def(rng: random.Random) -> Tuple[str, str, float, float, str]:
    """Pick a wire definition using realistic weighting (70% 0.5mm²)."""
    choices = WIRE_LIBRARY
    weights = [w for *_, w in choices]
    total = sum(weights)
    r = rng.random() * total
    cumulative = 0.0
    for entry in choices:
        cumulative += entry[-1]
        if r <= cumulative:
            return entry[:5]
    return choices[2][:5]  # fallback: FLRY-0.5-RD


# ── Main harness generator ────────────────────────────────────────────────────

def generate_harness(
    harness_idx: int,
    tier: str,
    topology: str,
    n_connectors: int,
    n_wires: int,
    cavities_override: Optional[List[int]] = None,
) -> WireHarness:
    rng = random.Random(harness_idx * 31337 + 17)

    # 1. Build topology (nodes + segments)
    if topology == "backbone":
        nodes, segments, connector_node_ids = _build_backbone_topology(rng, n_connectors)
    elif topology == "tree":
        nodes, segments, connector_node_ids = _build_tree_topology(rng, n_connectors)
    elif topology == "star":
        nodes, segments, connector_node_ids = _build_star_topology(rng, n_connectors)
    else:  # linear
        nodes, segments, connector_node_ids = _build_linear_topology(rng, n_connectors)

    # Ensure we have exactly n_connectors connector node IDs
    # (tree/backbone may sometimes produce fewer due to clipping — pad if needed)
    while len(connector_node_ids) < n_connectors:
        extra_idx = len(connector_node_ids)
        fallback_node = Node(
            id=f"conn_{extra_idx}",
            position=CartesianPoint(
                coord_x=_clamp(X_MID + rng.uniform(-300, 300), X_MIN + 30, X_MAX - 30),
                coord_y=_clamp(450 + rng.uniform(-200, 200), Y_MIN + 30, Y_MAX - 30),
            )
        )
        # Connect to first trunk node or root
        attach = nodes[0]
        nodes.append(fallback_node)
        segments.append(Segment(
            id=f"seg_fallback_{extra_idx}",
            start_node=attach,
            end_node=fallback_node,
            length=_node_dist(attach, fallback_node),
        ))
        connector_node_ids.append(fallback_node.id)

    # Build a map from node_id → Node
    node_map = {n.id: n for n in nodes}

    # 2. Determine cavity count per connector.
    #    If an explicit distribution is provided (pin sweep mode), use it directly.
    #    Otherwise distribute n_wires*2 endpoints evenly and round to standard sizes.
    if cavities_override is not None:
        cavities_per_conn = list(cavities_override)
    else:
        total_cavities_needed = n_wires * 2
        cavities_per_conn = [max(1, total_cavities_needed // n_connectors)] * n_connectors
        remainder = total_cavities_needed - sum(cavities_per_conn)
        for i in range(remainder):
            cavities_per_conn[i] += 1
        cavities_per_conn = [_round_to_connector_size(c) for c in cavities_per_conn]

    # 3. Build connector definitions
    terminal = Terminal(
        id="term_std",
        part_number="TERM-PIN-0.5",
        terminal_type="pin",
        gender="male",
        min_cross_section_mm=0.35,
        max_cross_section_mm=1.5,
    )

    conn_defs = []
    conn_occs = []
    # Per-connector cavity pools (available ContactPoints)
    cavity_pools: List[List[ContactPoint]] = []

    for ci, (node_id, n_cav) in enumerate(zip(connector_node_ids, cavities_per_conn)):
        pn, ct, _ = _pick_connector_def(rng, n_cav)
        slot = Slot(
            id=f"slot_c{ci}_1",
            slot_number="1",
            num_cavities=n_cav,
            gender="female",
        )
        conn_def = Connector(
            id=f"def_conn_{ci}",
            part_number=pn,
            connector_type=ct,
            slots=[slot],
        )
        conn_defs.append(conn_def)

        cavities = [
            Cavity(id=f"cav_c{ci}_{k}", cavity_number=str(k + 1))
            for k in range(n_cav)
        ]
        contact_points = [
            ContactPoint(id=f"cp_c{ci}_{k}", terminal=terminal, cavity=cavities[k])
            for k in range(n_cav)
        ]
        cavity_pools.append(contact_points)

        w, h = _connector_dims(n_cav)
        conn_occ = ConnectorOccurrence(
            id=f"Conn_{ci:03d}",
            connector=conn_def,
            label=f"C{ci:03d}",
            node_id=node_id,
            physical_width=w,
            physical_height=h,
            mating_direction=rng.choice(MATING_DIRECTIONS),
            contact_points=contact_points,
        )
        conn_occs.append(conn_occ)

    # 4. Build segment graph for path finding
    graph = _build_graph(segments)

    # 5. Assign wires to connector pairs
    #    Each cavity pool is consumed FIFO; once exhausted, skip that connector
    #    Build a list of (conn_idx_a, conn_idx_b) wire assignments
    pool_ptr = [0] * n_connectors  # next available cavity index per connector

    wire_defs: List[Wire] = []
    wire_occs: List[WireOccurrence] = []
    connections: List[Connection] = []

    # Build a shuffled list of (a, b) pairs to consume, ensuring balance
    wire_pairs = _generate_wire_pairs(rng, n_connectors, n_wires, cavities_per_conn)

    wire_idx = 0
    for (ci_a, ci_b) in wire_pairs:
        if wire_idx >= n_wires:
            break
        # Consume cavities
        cp_a = cavity_pools[ci_a][pool_ptr[ci_a]]
        cp_b = cavity_pools[ci_b][pool_ptr[ci_b]]
        pool_ptr[ci_a] += 1
        pool_ptr[ci_b] += 1

        # Find path segments
        node_a_id = connector_node_ids[ci_a]
        node_b_id = connector_node_ids[ci_b]
        path_segs = _find_path_segments(graph, node_a_id, node_b_id)
        if path_segs is None:
            # No path — skip (shouldn't happen with connected topologies)
            continue

        # Wire length = sum of path segment lengths + 10% production slack
        total_path_len = sum(s.length for s in path_segs if s.length)

        pn, wtype, xsec, od, color = _pick_wire_def(rng)
        w_def_id = f"def_wire_{pn}_{wire_idx}"
        wire_def = Wire(
            id=w_def_id,
            part_number=pn,
            wire_type=wtype,
            cross_section_area_mm2=xsec,
            outside_diameter=od,
            material_conductor="Copper",
            material_insulation="PVC",
            cover_colors=[WireColor(color_type="Base Color", color_code=color)],
        )
        wire_defs.append(wire_def)

        wire_occ = WireOccurrence(
            id=f"wire_{wire_idx:04d}",
            wire=wire_def,
            wire_number=f"W{wire_idx + 1:04d}",
            length_dmu=round(total_path_len, 1),
            length_production=round(total_path_len * 1.10, 1),
        )
        wire_occs.append(wire_occ)

        conn = Connection(
            id=f"conn_{wire_idx:04d}",
            signal_name=f"SIG_{wire_idx + 1:04d}",
            wire_occurrence=wire_occ,
            extremities=[
                Extremity(id=f"ext_{wire_idx}_a", position_on_wire=0.0, contact_point=cp_a),
                Extremity(id=f"ext_{wire_idx}_b", position_on_wire=1.0, contact_point=cp_b),
            ],
            segments=path_segs,
        )
        connections.append(conn)
        wire_idx += 1

    return WireHarness(
        id=f"synthetic_{harness_idx:03d}",
        part_number=f"SYN-{tier.upper()}-{harness_idx:03d}",
        version="1.0",
        company_name="Synthetic Generator",
        description=f"Synthetic {tier} harness ({topology}): {n_connectors} connectors, {wire_idx} wires",
        created_at="2026-04-13T00:00:00",
        connectors=conn_defs,
        terminals=[terminal],
        wires=wire_defs,
        connector_occurrences=conn_occs,
        wire_occurrences=wire_occs,
        connections=connections,
        nodes=nodes,
        segments=segments,
    )


def _round_to_connector_size(n: int) -> int:
    """Round up to the nearest standard connector cavity count."""
    for size in [3, 6, 12, 24, 36, 48]:
        if n <= size:
            return size
    return n  # oversized — keep as-is


def _generate_wire_pairs(
    rng: random.Random,
    n_connectors: int,
    n_wires: int,
    capacities: List[int],
) -> List[Tuple[int, int]]:
    """
    Generate a list of (conn_a, conn_b) pairs for wire assignments.
    Each connector ci is used at most capacities[ci] times total (across both endpoints).
    Tries to distribute connections realistically (ECU-like connector connects to many others).
    """
    # Track remaining capacity per connector
    remaining = list(capacities)
    pairs = []

    # Build a candidate pool: all (a, b) pairs
    # Weight by combined remaining capacity to favour high-capacity connectors
    attempts = 0
    while len(pairs) < n_wires and attempts < n_wires * 10:
        attempts += 1
        # Pick first connector weighted by remaining capacity
        total_cap = sum(remaining)
        if total_cap < 2:
            break
        r = rng.random() * total_cap
        ci_a = 0
        cumulative = 0
        for i, cap in enumerate(remaining):
            cumulative += cap
            if r <= cumulative:
                ci_a = i
                break

        if remaining[ci_a] < 1:
            continue

        # Pick second connector: any other with remaining capacity
        candidates = [i for i in range(n_connectors) if i != ci_a and remaining[i] > 0]
        if not candidates:
            break
        ci_b = rng.choice(candidates)

        pairs.append((ci_a, ci_b))
        remaining[ci_a] -= 1
        remaining[ci_b] -= 1

    return pairs


# ── Tier configuration ────────────────────────────────────────────────────────

TIERS = [
    # (tier_name, n_variants, conn_range, wire_range, topologies_with_weights)
    ("tiny",    15, (2, 3),   (2, 10),   [("linear", 1.0)]),
    ("small",   25, (4, 6),   (11, 40),  [("backbone", 0.6), ("tree", 0.4)]),
    ("medium",  30, (7, 12),  (41, 80),  [("backbone", 0.5), ("tree", 0.3), ("star", 0.2)]),
    ("large",   20, (13, 20), (81, 140), [("backbone", 0.5), ("tree", 0.35), ("star", 0.15)]),
    ("complex", 10, (21, 30), (141, 200), [("backbone", 0.6), ("tree", 0.3), ("star", 0.1)]),
]


def _weighted_choice(rng: random.Random, options: List[Tuple[str, float]]) -> str:
    total = sum(w for _, w in options)
    r = rng.random() * total
    cumulative = 0.0
    for name, w in options:
        cumulative += w
        if r <= cumulative:
            return name
    return options[0][0]


def _random_partition(rng: random.Random, total: int, n_parts: int) -> List[int]:
    """
    Split *total* into *n_parts* positive integers (each ≥ 1) chosen uniformly
    at random among all such partitions (stars-and-bars via sorted cut-points).
    """
    assert total >= n_parts >= 1
    remainder = total - n_parts          # distribute this on top of the 1-floor
    cuts = sorted(rng.randint(0, remainder) for _ in range(n_parts - 1))
    cuts = [0] + cuts + [remainder]
    return [1 + cuts[i + 1] - cuts[i] for i in range(n_parts)]


def _n_connectors_for_pins(rng: random.Random, total_pins: int) -> int:
    """Choose a random connector count appropriate for the given total pin count."""
    if total_pins <= 6:
        return 2
    elif total_pins <= 20:
        return rng.randint(2, 4)
    elif total_pins <= 40:
        return rng.randint(3, 6)
    else:
        return rng.randint(4, 8)


def _save_harness(harness: WireHarness, out_path: Path) -> None:
    harness_dict = harness.model_dump()
    harness_dict["connector_occurrences"] = [
        occ.model_dump() for occ in harness.connector_occurrences
    ]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(harness_dict, f, indent=2)


def _pin_sweep(n: int, max_pins: int) -> List[int]:
    """
    Return n even pin counts linearly spaced from 2 to max_pins.
    Values are rounded to the nearest even number, so counts near the same
    step repeat — giving multiple harness variants at the same pin count.
    """
    result = []
    for i in range(n):
        raw = 2 + (max_pins - 2) * i / max(n - 1, 1)
        even = max(2, round(raw / 2) * 2)
        result.append(even)
    return result


def main(max_pins: int = MAX_PINS, n_harnesses: int = N_HARNESSES) -> None:
    if max_pins % 2 != 0:
        max_pins -= 1

    output_dir = Path(__file__).parent / "generated"
    output_dir.mkdir(exist_ok=True)

    # Remove stale harness files so only the current sweep remains
    for stale in output_dir.glob("harness_*.json"):
        stale.unlink()

    topology_weights = [("backbone", 0.5), ("tree", 0.3), ("star", 0.2)]

    pin_counts = _pin_sweep(n_harnesses, max_pins)
    manifest = []
    harness_idx = 0

    print(f"Generating {n_harnesses} harnesses (2 … {max_pins} pins, {len(set(pin_counts))} distinct counts)\n")

    for total_pins in pin_counts:
        n_wires = total_pins // 2
        # Unique seed per harness index so same pin count → different distribution
        rng = random.Random(harness_idx * 31337 + 42)

        n_connectors = _n_connectors_for_pins(rng, total_pins)

        # Distribute pins unevenly across connectors (each gets ≥ 1)
        pin_dist = _random_partition(rng, total_pins, n_connectors)
        # Overwrite cavities_per_conn in generate_harness via explicit argument
        topology = _weighted_choice(rng, topology_weights)

        harness = generate_harness(
            harness_idx, "pinsweep", topology, n_connectors, n_wires,
            cavities_override=pin_dist,
        )

        actual_wires = len(harness.wire_occurrences)
        actual_connectors = len(harness.connector_occurrences)
        total_len = sum(s.length for s in harness.segments if s.length)

        out_path = output_dir / f"harness_{harness_idx:03d}.json"
        _save_harness(harness, out_path)

        manifest.append({
            "harness_id": f"harness_{harness_idx:03d}",
            "total_pins": total_pins,
            "n_connectors": actual_connectors,
            "pin_distribution": "+".join(str(p) for p in pin_dist),
            "topology": topology,
            "n_wires": actual_wires,
            "total_wire_length_mm": round(total_len, 1),
        })

        print(f"  [{harness_idx:03d}] {total_pins:3d} pins  "
              f"{n_connectors} connectors ({'+'.join(str(p) for p in pin_dist)})  "
              f"{actual_wires} wires  {topology}  → {out_path.name}")

        harness_idx += 1

    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8") as f:
        header = list(manifest[0].keys())
        f.write(",".join(header) + "\n")
        for row in manifest:
            f.write(",".join(str(row[k]) for k in header) + "\n")

    print(f"\n✓ {harness_idx} harnesses written to {output_dir}")
    print(f"✓ Manifest → {manifest_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Generate pin-sweep synthetic harnesses.")
    ap.add_argument("--max-pins", type=int, default=MAX_PINS,
                    help=f"Maximum total pin count, even (default {MAX_PINS})")
    ap.add_argument("--n", type=int, default=N_HARNESSES,
                    help=f"Number of harnesses to generate (default {N_HARNESSES})")
    args = ap.parse_args()
    main(max_pins=args.max_pins, n_harnesses=args.n)
