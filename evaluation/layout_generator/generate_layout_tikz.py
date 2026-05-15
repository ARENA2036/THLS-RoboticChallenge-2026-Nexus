"""
Generate TikZ figures for both medium and complex harness layouts.

Outputs:
    698f3ae54d2ddb0627e27162/figures/layout_medium.tex
    698f3ae54d2ddb0627e27162/figures/layout_complex.tex
    698f3ae54d2ddb0627e27162/figures/layout_comparison.tex  (side-by-side wrapper)

Run from project root:
    python layout_generator/examples/generate_layout_tikz.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from public.cdm.examples import load_example
from layout_generator.LayoutGeneratorService import LayoutGeneratorService
from layout_generator.LayoutModels import (
    BoardConfig, LayoutParameters, LayoutRequest, PegPlacementReason,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIGURES_DIR = PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures"

# Visual scale: layout mm → TikZ cm.  Both harnesses drawn at the same scale
# so sizes remain physically comparable.
SCALE = 0.006  # cm per layout-mm  →  medium ≈ 4.3×3.2 cm, complex ≈ 7.0×4.9 cm

# ── geometry helpers ──────────────────────────────────────────────────────────

def _coord(x_mm: float, y_mm: float) -> str:
    """Return TikZ coordinate string."""
    return f"({x_mm * SCALE:.4f},{y_mm * SCALE:.4f})"


def _rect_corners(cx: float, cy: float, w: float, h: float, angle_deg: float):
    """Return four corners of a rotated rectangle (all in layout-mm)."""
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    rotated = []
    for dx, dy in corners:
        rx = cx + dx * cos_a - dy * sin_a
        ry = cy + dx * sin_a + dy * cos_a
        rotated.append((rx, ry))
    return rotated


def _arrow_endpoint(cx: float, cy: float, angle_deg: float, length: float = 30):
    """Return the tip of an orientation arrow."""
    rad = math.radians(angle_deg)
    return cx + length * math.cos(rad), cy + length * math.sin(rad)


# ── TikZ builder ──────────────────────────────────────────────────────────────

def build_harness_tikz(harness_name: str) -> tuple[str, dict]:
    """
    Generate TikZ source for one harness layout.
    Returns (tikz_body, stats_dict).
    """
    harness = load_example(harness_name)
    all_x = [n.position.coord_x for n in harness.nodes]
    all_y = [n.position.coord_y for n in harness.nodes]
    margin = 80
    board_config = BoardConfig(
        width_mm=max(all_x) - min(all_x) + 2 * margin,
        height_mm=max(all_y) - min(all_y) + 2 * margin,
        offset_x=-min(all_x) + margin,
        offset_y=-min(all_y) + margin,
    )
    layout = LayoutGeneratorService().generate_layout(
        LayoutRequest(harness=harness, board_config=board_config, parameters=LayoutParameters())
    )

    ox, oy = board_config.offset_x, board_config.offset_y
    W, H = board_config.width_mm, board_config.height_mm
    lines = []

    # Board outline
    lines.append(f"  % board outline")
    lines.append(
        f"  \\draw[draw=gray!50, fill=gray!8, line width=0.4pt] "
        f"(0,0) rectangle {_coord(W, H)};"
    )

    # Wire topology: draw each segment as a straight line between its node positions
    lines.append(f"  % wire segments")
    node_by_id = {n.id: n for n in harness.nodes}
    for seg in harness.segments:
        sn = node_by_id.get(seg.start_node.id if hasattr(seg.start_node, 'id') else seg.start_node)
        en = node_by_id.get(seg.end_node.id if hasattr(seg.end_node, 'id') else seg.end_node)
        if sn is None or en is None:
            sn = seg.start_node
            en = seg.end_node
        sx = sn.position.coord_x + ox
        sy = sn.position.coord_y + oy
        ex = en.position.coord_x + ox
        ey = en.position.coord_y + oy
        lines.append(
            f"  \\draw[gray!70, line width=0.5pt] {_coord(sx, sy)} -- {_coord(ex, ey)};"
        )

    # Interval pegs — small gray circles
    lines.append(f"  % interval pegs")
    for peg in layout.pegs:
        if peg.reason == PegPlacementReason.INTERVAL:
            lines.append(
                f"  \\fill[gray!55] {_coord(peg.position.x, peg.position.y)} circle (1.2pt);"
            )
            lines.append(
                f"  \\draw[gray!70, line width=0.3pt] "
                f"{_coord(peg.position.x, peg.position.y)} circle (1.2pt);"
            )

    # Breakout pegs — slightly larger green circles
    lines.append(f"  % breakout pegs")
    for peg in layout.pegs:
        if peg.reason == PegPlacementReason.BREAKOUT_POINT:
            lines.append(
                f"  \\fill[green!55!black] {_coord(peg.position.x, peg.position.y)} circle (1.6pt);"
            )
            lines.append(
                f"  \\draw[green!40!black, line width=0.3pt] "
                f"{_coord(peg.position.x, peg.position.y)} circle (1.6pt);"
            )

    # Connector holders — rotated blue rectangles + orientation arrow
    lines.append(f"  % connector holders")
    for holder in layout.connector_holders:
        cx, cy = holder.position.x, holder.position.y
        w, h = holder.width_mm, holder.height_mm
        ang = holder.orientation_deg

        corners = _rect_corners(cx, cy, w, h, ang)
        pts = " -- ".join(_coord(rx, ry) for rx, ry in corners)
        lines.append(
            f"  \\fill[blue!45!white, draw=blue!60!black, line width=0.35pt, opacity=0.85] "
            f"{pts} -- cycle;"
        )
        # Mating-direction arrow
        ax, ay = _arrow_endpoint(cx, cy, ang, length=h * 0.75)
        lines.append(
            f"  \\draw[-{{Stealth[length=2pt,width=1.5pt]}}, blue!70!black, line width=0.5pt] "
            f"{_coord(cx, cy)} -- {_coord(ax, ay)};"
        )

    tikz_body = "\n".join(lines)

    # Stats
    from layout_generator.LayoutModels import PegPlacementReason as PPR
    stats = {
        "wires": len(harness.wires),
        "segments": len(harness.segments),
        "nodes": len(harness.nodes),
        "connectors": len(harness.connector_occurrences),
        "total_length_mm": int(sum(s.length for s in harness.segments if s.length)),
        "board_w": int(W),
        "board_h": int(H),
        "pegs_total": len(layout.pegs),
        "pegs_breakout": sum(1 for p in layout.pegs if p.reason == PPR.BREAKOUT_POINT),
        "pegs_interval": sum(1 for p in layout.pegs if p.reason == PPR.INTERVAL),
        "holders": len(layout.connector_holders),
        "utilization": layout.metrics.board_utilization_percent,
        "tikz_width_cm": W * SCALE,
        "tikz_height_cm": H * SCALE,
    }
    return tikz_body, stats


def write_single_layout(harness_name: str, output_path: Path) -> dict:
    tikz_body, stats = build_harness_tikz(harness_name)
    W_cm = stats["tikz_width_cm"]
    H_cm = stats["tikz_height_cm"]

    content = f"""%% Auto-generated TikZ layout for {harness_name} harness.
%% Include with: \\input{{figures/layout_{harness_name}.tex}}
%% Requires: \\usetikzlibrary{{arrows.meta}}
\\begin{{tikzpicture}}[x=1cm, y=1cm, scale=1]
{tikz_body}
\\end{{tikzpicture}}
"""
    output_path.write_text(content)
    print(f"  Wrote {output_path.name}  ({W_cm:.2f} × {H_cm:.2f} cm)")
    return stats


def write_combined_tikz(
    body_m: str, stats_m: dict,
    body_c: str, stats_c: dict,
    output_path: Path,
    gap_cm: float = 0.35,
) -> None:
    """Write both layouts into a single tikzpicture, medium left, complex right."""
    W_m = stats_m["tikz_width_cm"]
    H_m = stats_m["tikz_height_cm"]
    W_c = stats_c["tikz_width_cm"]
    H_c = stats_c["tikz_height_cm"]

    label_style = "font=\\footnotesize\\bfseries, anchor=south west"

    content = f"""%% Auto-generated combined TikZ layout (medium + complex).
%% Requires: \\usetikzlibrary{{arrows.meta}}
\\begin{{tikzpicture}}[x=1cm, y=1cm]
  %% ── (a) Medium harness ──────────────────────────────────────────────
{body_m}
  \\node[{label_style}] at (0, {H_m:.4f}) {{(a)}};
  %% ── (b) Complex harness (shifted right) ────────────────────────────
  \\begin{{scope}}[xshift={W_m + gap_cm:.4f}cm]
{body_c}
    \\node[{label_style}] at (0, {H_c:.4f}) {{(b)}};
  \\end{{scope}}
\\end{{tikzpicture}}
"""
    output_path.write_text(content)
    print(f"  Wrote {output_path.name}  "
          f"({W_m + gap_cm + W_c:.2f} × {max(H_m, H_c):.2f} cm combined)")


def write_comparison_wrapper(stats_m: dict, stats_c: dict, output_path: Path) -> None:
    """Write a compact single-column figure wrapping layout_both.tex."""
    content = """%% Compact single-column layout comparison figure.
%% Requires subcaption, tikz, arrows.meta.
\\begin{figure}[htbp]
  \\centering
  \\resizebox{\\columnwidth}{!}{\\input{figures/layout_both.tex}}
  \\caption{%
    Assembly board layouts derived from CDM data for the medium~(a) and
    complex~(b) harness variants.
    \\textcolor{blue!60!black}{$\\blacksquare$}~connector holders (mating-direction arrow);
    \\textcolor{green!50!black}{$\\bullet$}~breakout peg;
    \\textcolor{gray!60}{$\\bullet$}~interval peg.
  }
  \\label{fig:layout-comparison}
\\end{figure}
"""
    output_path.write_text(content)
    print(f"  Wrote {output_path.name}")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating TikZ layout figures...")

    body_m, stats_m = build_harness_tikz("medium")
    body_c, stats_c = build_harness_tikz("complex")

    write_single_layout("medium",  FIGURES_DIR / "layout_medium.tex")
    write_single_layout("complex", FIGURES_DIR / "layout_complex.tex")
    write_combined_tikz(body_m, stats_m, body_c, stats_c, FIGURES_DIR / "layout_both.tex")
    write_comparison_wrapper(stats_m, stats_c, FIGURES_DIR / "layout_comparison.tex")

    print("\nDone. Include in LaTeX with:")
    print("  \\input{figures/layout_comparison.tex}")
    print("\nStatistics summary:")
    for label, s, dur, mot in [("medium", stats_m, 111.9, 7), ("complex", stats_c, 218.9, 17)]:
        print(f"  {label}: {s['wires']} wires, {s['connectors']} connectors, "
              f"{s['segments']} segs, {s['total_length_mm']} mm total, "
              f"{s['board_w']}×{s['board_h']} mm board, "
              f"{s['pegs_total']} pegs ({s['pegs_breakout']} breakout + {s['pegs_interval']} interval), "
              f"{s['holders']} holders, {dur:.0f}s sim, {mot} motions")
