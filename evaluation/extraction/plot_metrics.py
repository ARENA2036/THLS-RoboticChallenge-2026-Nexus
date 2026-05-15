"""Plot precision/recall vs. harness size from an eval report.json.

Produces one figure with two rows:
  Row 1 — Connectors: precision, recall vs. #GT connectors (per case + rolling mean).
  Row 2 — Connections (wires): strict + loose precision/recall vs. #GT connections.

Usage:
    python eval/plot_metrics.py --report eval/output/runs/report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


def _rolling_mean(xs: np.ndarray, ys: np.ndarray, bins: int = 10) -> Tuple[np.ndarray, np.ndarray]:
    """Bucket points by x into equal-width bins and return (bin_centers, mean_y)."""
    if xs.size == 0:
        return np.array([]), np.array([])
    lo, hi = xs.min(), xs.max()
    if lo == hi:
        return np.array([lo]), np.array([ys.mean()])
    edges = np.linspace(lo, hi, bins + 1)
    centers, means = [], []
    for i in range(bins):
        m = (xs >= edges[i]) & (xs < edges[i + 1] if i < bins - 1 else xs <= edges[i + 1])
        if m.any():
            centers.append((edges[i] + edges[i + 1]) / 2)
            means.append(ys[m].mean())
    return np.array(centers), np.array(means)


def _scatter_with_trend(ax, xs, ys, label, color, bins=10, ylabel=None):
    ax.scatter(xs, ys, s=18, alpha=0.35, color=color, label=f"{label} (per case)")
    bc, bm = _rolling_mean(xs, ys, bins=bins)
    if bc.size:
        ax.plot(bc, bm, "-", color=color, linewidth=2.2, label=f"{label} (binned mean)")
    ax.set_ylim(-0.02, 1.02)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower left", fontsize=8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path,
                    default=Path("eval/output/runs/report.json"))
    ap.add_argument("--out", type=Path, default=Path("eval/output/metrics_plot.png"))
    ap.add_argument("--bins", type=int, default=10)
    args = ap.parse_args()

    data = json.loads(args.report.read_text())
    cases = data.get("cases", [])

    n_conn: List[int] = []
    n_wire: List[int] = []
    conn_p: List[float] = []
    conn_r: List[float] = []
    wire_sp: List[float] = []
    wire_sr: List[float] = []
    wire_lp: List[float] = []
    wire_lr: List[float] = []

    for c in cases:
        fp_c = c.get("fp_connector") or {}
        fp_w = c.get("fp_connectivity") or {}
        n_conn.append(int(c.get("n_gt_connectors", 0)))
        n_wire.append(int(c.get("n_gt_connections", 0)))
        conn_p.append(float(fp_c.get("precision", 0.0)))
        conn_r.append(float(fp_c.get("recall", 0.0)))
        wire_sp.append(float(fp_w.get("strict_precision", 0.0)))
        wire_sr.append(float(fp_w.get("strict_recall", 0.0)))
        wire_lp.append(float(fp_w.get("loose_precision", 0.0)))
        wire_lr.append(float(fp_w.get("loose_recall", 0.0)))

    xc = np.array(n_conn)
    xw = np.array(n_wire)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharey=True)
    fig.suptitle(
        f"Extractor precision/recall vs. harness size "
        f"(n={len(cases)}, part-number identity)",
        fontsize=12, fontweight="bold",
    )

    # Row 1: connectors
    _scatter_with_trend(axes[0, 0], xc, np.array(conn_p),
                        "Precision", "#1f77b4", bins=args.bins, ylabel="Connector score")
    axes[0, 0].set_title("Connectors — Precision")
    axes[0, 0].set_xlabel("# GT connectors")

    _scatter_with_trend(axes[0, 1], xc, np.array(conn_r),
                        "Recall", "#d62728", bins=args.bins)
    axes[0, 1].set_title("Connectors — Recall")
    axes[0, 1].set_xlabel("# GT connectors")

    # Row 2: connections — matching-connectivity (primary) + matching-name (deprecated)
    ax_p = axes[1, 0]
    _scatter_with_trend(ax_p, xw, np.array(wire_sp),
                        "Matching connectivity — P", "#2ca02c",
                        bins=args.bins, ylabel="Connection score")
    _scatter_with_trend(ax_p, xw, np.array(wire_lp),
                        "Matching name — P (deprecated)", "#9467bd",
                        bins=args.bins)
    ax_p.set_title("Connections — Precision")
    ax_p.set_xlabel("# GT connections")

    ax_r = axes[1, 1]
    _scatter_with_trend(ax_r, xw, np.array(wire_sr),
                        "Matching connectivity — R", "#2ca02c", bins=args.bins)
    _scatter_with_trend(ax_r, xw, np.array(wire_lr),
                        "Matching name — R (deprecated)", "#9467bd", bins=args.bins)
    ax_r.set_title("Connections — Recall")
    ax_r.set_xlabel("# GT connections")

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=160)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
