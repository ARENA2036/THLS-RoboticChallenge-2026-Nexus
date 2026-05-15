"""
Generate the 2-panel scalability figure from the batch evaluation results.

Panel A (left):  Scatter — IK pre-planning time vs. total wire count,
                 coloured by topology type.
Panel B (right): Box plot — IK pre-planning time distribution per
                 complexity tier.

Output: 698f3ae54d2ddb0627e27162/figures/scalability_evaluation.pdf

Run from project root:
    simulation/venv/bin/python simulation/examples/generate_scalability_figure.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

RESULTS_CSV = PROJECT_ROOT / "public" / "cdm" / "examples" / "generated" / "evaluation_results.csv"
OUTPUT_PDF = PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures" / "scalability_evaluation.pdf"

# ── Styling ───────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 7,
    "axes.titlesize": 7,
    "axes.labelsize": 7,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,
    "lines.linewidth": 0.8,
    "axes.linewidth": 0.6,
    "grid.linewidth": 0.4,
    "grid.alpha": 0.4,
})

TOPOLOGY_COLORS = {
    "backbone": "#2166ac",
    "tree":     "#4dac26",
    "star":     "#d01c8b",
    "linear":   "#f1a340",
}
TOPOLOGY_MARKERS = {
    "backbone": "o",
    "tree":     "s",
    "star":     "^",
    "linear":   "D",
}

TIER_ORDER = ["tiny", "small", "medium", "large", "complex"]
TIER_LABELS = ["Tiny\n(2–3 C)", "Small\n(4–6 C)", "Medium\n(7–12 C)", "Large\n(13–20 C)", "Complex\n(21–30 C)"]
TIER_COLOR = "#555555"


def load_results(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    if not RESULTS_CSV.exists():
        print(f"Results CSV not found: {RESULTS_CSV}")
        sys.exit(1)

    rows = load_results(RESULTS_CSV)
    if not rows:
        print("Results CSV is empty.")
        sys.exit(1)

    # Parse numeric fields
    for row in rows:
        row["n_wires"] = int(row["n_wires"])
        row["t_ik_ms"] = float(row["t_ik_ms"])
        row["t_total_planning_ms"] = float(row["t_total_planning_ms"])
        row["n_connectors"] = int(row["n_connectors"])
        row["n_motions"] = int(row["n_motions"])

    n_total = len(rows)
    print(f"Loaded {n_total} feasible variants")

    # ── Figure layout ─────────────────────────────────────────────────────────
    fig_width_in = 7.16   # IEEE double-column width
    fig_height_in = 2.8
    fig, (ax_scatter, ax_box) = plt.subplots(
        1, 2,
        figsize=(fig_width_in, fig_height_in),
        gridspec_kw={"width_ratios": [1.4, 1]},
    )

    # ── Panel A: Scatter ──────────────────────────────────────────────────────
    for topology, color in TOPOLOGY_COLORS.items():
        subset = [r for r in rows if r["topology"] == topology]
        if not subset:
            continue
        xs = [r["n_wires"] for r in subset]
        ys = [r["t_ik_ms"] / 1000 for r in subset]   # ms → s
        marker = TOPOLOGY_MARKERS[topology]
        ax_scatter.scatter(
            xs, ys,
            label=topology.capitalize(),
            color=color,
            marker=marker,
            s=14,
            alpha=0.78,
            linewidths=0.3,
            edgecolors="white",
            zorder=3,
        )

    ax_scatter.set_xlabel("Number of wires")
    ax_scatter.set_ylabel("IK pre-planning time (s)")
    ax_scatter.set_yscale("log")
    ax_scatter.yaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: f"{y:.0f}" if y >= 1 else f"{y:.1f}"))
    ax_scatter.grid(True, which="both", linestyle="--")
    ax_scatter.legend(
        title="Topology",
        loc="upper left",
        framealpha=0.85,
        handlelength=1.2,
        handletextpad=0.4,
        borderpad=0.4,
    )
    ax_scatter.set_title("(a) IK planning time vs. wire count")

    # Annotate median
    all_ik_s = sorted(r["t_ik_ms"] / 1000 for r in rows)
    median_s = all_ik_s[len(all_ik_s) // 2]
    ax_scatter.axhline(median_s, color="gray", linestyle=":", linewidth=0.7, zorder=2)
    ax_scatter.text(
        ax_scatter.get_xlim()[1] if ax_scatter.get_xlim()[1] > 0 else 200,
        median_s * 1.15,
        f"median {median_s:.1f} s",
        ha="right", va="bottom", fontsize=5.5, color="gray",
    )

    # ── Panel B: Box plot ─────────────────────────────────────────────────────
    box_data = []
    box_labels = []
    for tier, label in zip(TIER_ORDER, TIER_LABELS):
        subset = [r["t_ik_ms"] / 1000 for r in rows if r["tier"] == tier]
        if subset:
            box_data.append(subset)
            box_labels.append(label + f"\n(n={len(subset)})")

    bp = ax_box.boxplot(
        box_data,
        patch_artist=True,
        notch=False,
        vert=True,
        widths=0.5,
        flierprops=dict(marker="x", markersize=3, markeredgewidth=0.5, color="#888888"),
        medianprops=dict(color="black", linewidth=1.0),
        whiskerprops=dict(linewidth=0.7),
        capprops=dict(linewidth=0.7),
        boxprops=dict(linewidth=0.7),
    )
    # Colour boxes by tier
    tier_colors = ["#d4e6f1", "#a9dfbf", "#fdebd0", "#f9e4b7", "#f5cba7"]
    for patch, color in zip(bp["boxes"], tier_colors[:len(bp["boxes"])]):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)

    ax_box.set_yscale("log")
    ax_box.yaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: f"{y:.0f}" if y >= 1 else f"{y:.1f}"))
    ax_box.set_xticklabels(box_labels, fontsize=5.5)
    ax_box.set_ylabel("IK pre-planning time (s)")
    ax_box.grid(True, which="both", axis="y", linestyle="--")
    ax_box.set_title("(b) Time distribution per complexity tier")

    # ── Summary annotation ────────────────────────────────────────────────────
    p95_s = all_ik_s[int(len(all_ik_s) * 0.95)]
    summary = (
        f"N={n_total} feasible variants  |  "
        f"median {median_s:.1f} s  |  "
        f"p95 {p95_s:.1f} s"
    )
    fig.text(0.5, 0.01, summary, ha="center", va="bottom", fontsize=5.5, color="#444444")

    fig.tight_layout(rect=[0, 0.04, 1, 1])

    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PDF, format="pdf", bbox_inches="tight", dpi=300)
    print(f"Saved → {OUTPUT_PDF}")

    # Also print key numbers for paper text
    print(f"\nKey numbers for paper:")
    print(f"  Feasible variants: {n_total}/100")
    print(f"  IK median: {median_s:.1f} s")
    print(f"  IK p95:    {p95_s:.1f} s")
    print(f"  IK max:    {all_ik_s[-1]:.1f} s")
    print(f"  IK min:    {all_ik_s[0]:.1f} s")

    by_tier = {}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(r["t_ik_ms"] / 1000)
    for tier in TIER_ORDER:
        if tier in by_tier:
            vals = sorted(by_tier[tier])
            print(f"  {tier:8s}: n={len(vals)}, median={vals[len(vals)//2]:.1f}s, max={vals[-1]:.1f}s")


if __name__ == "__main__":
    main()
