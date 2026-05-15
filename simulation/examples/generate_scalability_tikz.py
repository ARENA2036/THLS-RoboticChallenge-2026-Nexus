"""
Generate a 2-panel pgfplots TikZ figure from the full-simulation batch results.

Panel A:  Scatter — board-setup execution time (s, log) vs. number of wires,
          one point per CDM, coloured/shaped by topology type.
Panel B:  Scatter — wire-routing execution time (s, log) vs. number of wires,
          same topology encoding.

x-axis (both panels): number of wire occurrences in the CDM.
y-axis (both panels): robot execution time in seconds (log scale).

Input:
    public/cdm/examples/generated/full_simulation_results.csv

Output:
    698f3ae54d2ddb0627e27162/figures/execution_times.tex
    698f3ae54d2ddb0627e27162/figures/scalability_wrapper.tex

Run from project root:
    simulation/venv/bin/python simulation/examples/generate_scalability_tikz.py
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS_CSV = (
    PROJECT_ROOT / "public" / "cdm" / "examples" / "generated"
    / "full_simulation_results.csv"
)
OUTPUT_TEX = (
    PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures"
    / "execution_times.tex"
)
OUTPUT_WRAPPER = (
    PROJECT_ROOT / "698f3ae54d2ddb0627e27162" / "figures"
    / "execution_times_figure.tex"
)

TOPO_ORDER = ["backbone", "tree", "star", "linear"]

# pgfplots mark + fill colour per topology
TOPO_STYLE: dict[str, tuple[str, str, str]] = {
    "backbone": ("o",         "blue!70!black",    "blue!50!black"),
    "tree":     ("square*",   "green!60!black",   "green!40!black"),
    "star":     ("triangle*", "orange!80!black",  "orange!60!black"),
    "linear":   ("diamond*",  "red!70!black",     "red!50!black"),
}
TOPO_LABEL: dict[str, str] = {
    "backbone": "Backbone",
    "tree":     "Tree",
    "star":     "Star",
    "linear":   "Linear",
}


def load_results(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                row["n_wires"]                 = int(row["n_wires"])
                row["n_connectors"]            = int(row["n_connectors"])
                row["board_setup_duration_s"]  = float(row["board_setup_duration_s"])
                row["wire_routing_duration_s"] = float(row["wire_routing_duration_s"])
                row["board_parallel_s"]        = float(row["board_parallel_s"])
                row["board_single_s"]          = float(row["board_single_s"])
                row["board_idle_s"]            = float(row["board_idle_s"])
                row["routing_parallel_s"]      = float(row["routing_parallel_s"])
                row["routing_single_s"]        = float(row["routing_single_s"])
                row["routing_idle_s"]          = float(row["routing_idle_s"])
                row["total_parallel_pct"]      = float(row["total_parallel_pct"])
                row["total_single_pct"]        = float(row["total_single_pct"])
                row["total_idle_pct"]          = float(row["total_idle_pct"])
                rows.append(row)
            except (ValueError, KeyError):
                continue
    return rows


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    return s[len(s) // 2]


def _percentile(vals: list[float], p: float) -> float:
    s = sorted(vals)
    return s[int(len(s) * p)]


def _nice_log_bounds(vals: list[float]) -> tuple[float, float]:
    """Return (ymin, ymax) rounded to nice powers-of-10 multiples."""
    lo = min(vals)
    hi = max(vals)
    ymin = 10 ** math.floor(math.log10(lo * 0.9))
    ymax = 10 ** math.ceil(math.log10(hi * 1.1))
    return ymin, ymax


def _log_yticks(ymin: float, ymax: float) -> list[float]:
    """Return decade ticks that fit inside [ymin, ymax]."""
    ticks = []
    v = 10 ** math.ceil(math.log10(ymin))
    while v <= ymax * 1.001:
        ticks.append(v)
        v *= 10
    return ticks


def main() -> None:
    if not RESULTS_CSV.exists():
        print(f"Results CSV not found: {RESULTS_CSV}")
        print("Run simulation/examples/run_batch_full_simulation.py first.")
        sys.exit(1)

    rows = load_results(RESULTS_CSV)
    if len(rows) < 5:
        print(f"Only {len(rows)} rows — rerun batch simulation first.")
        sys.exit(1)

    n_total = len(rows)
    print(f"Loaded {n_total} variants")

    # ── Per-topology groupings ────────────────────────────────────────────────
    by_topo: dict[str, list[dict]] = {}
    for r in rows:
        by_topo.setdefault(r["topology"], []).append(r)
    active_topos = [t for t in TOPO_ORDER if t in by_topo]

    # ── Summary statistics ────────────────────────────────────────────────────
    board_times   = [r["board_setup_duration_s"]  for r in rows]
    routing_times = [r["wire_routing_duration_s"] for r in rows]
    par_pcts      = [r["total_parallel_pct"]      for r in rows]
    single_pcts   = [r["total_single_pct"]        for r in rows]
    idle_pcts     = [r["total_idle_pct"]          for r in rows]

    board_med   = _median(board_times)
    routing_med = _median(routing_times)
    par_med     = _median(par_pcts)
    single_med  = _median(single_pcts)
    idle_med    = _median(idle_pcts)

    print(f"  Board setup:    median={board_med:.1f}s  max={max(board_times):.1f}s")
    print(f"  Wire routing:   median={routing_med:.1f}s  max={max(routing_times):.1f}s")
    print(f"  Parallel (med): {par_med:.0f}%  Single: {single_med:.0f}%  Idle: {idle_med:.0f}%")

    # ── Axis bounds ───────────────────────────────────────────────────────────
    x_max = max(r["n_wires"] for r in rows)
    x_max_nice = int(math.ceil(x_max / 25) * 25)  # round up to next multiple of 25

    def _nice_linear_max(vals: list[float]) -> float:
        """Round max up to a nice multiple for the y-axis."""
        hi = max(vals)
        magnitude = 10 ** math.floor(math.log10(hi))
        return math.ceil(hi / magnitude) * magnitude

    # ── Build TikZ ────────────────────────────────────────────────────────────
    L: list[str] = []

    def w(s: str = "") -> None:
        L.append(s)

    w(r"% Auto-generated by simulation/examples/generate_scalability_tikz.py")
    w(r"% Requires: \usepackage{pgfplots}")
    w(r"% \usepgfplotslibrary{groupplots}")
    w(r"% \pgfplotsset{compat=1.18}")
    w(r"\begin{tikzpicture}")
    w(r"\begin{groupplot}[")
    w(r"  group style={")
    w(r"    group size=1 by 2,")
    w(r"    vertical sep=0.9cm,")
    w(r"  },")
    w(r"  width=8.8cm,")
    w(r"  height=4.0cm,")
    w(r"  grid=both,")
    w(r"  grid style={line width=0.3pt, gray!35},")
    w(r"  major grid style={line width=0.45pt, gray!55},")
    w(r"  tick label style={font=\scriptsize},")
    w(r"  label style={font=\small},")
    w(r"  ylabel style={at={(axis description cs:-0.20,0.5)}, anchor=center},")
    w(r"  xmin=0,")
    w(rf"  xmax={x_max_nice},")
    w(r"  xtick distance=50,")
    w(r"  minor x tick num=4,")
    w(r"  ymin=0,")
    w(r"  legend style={font=\scriptsize, draw=none, fill=white,")
    w(r"    fill opacity=0.9, text opacity=1, inner sep=2pt, row sep=-2pt},")
    w(r"]")
    w()

    # ── Common scatter-plot macro ─────────────────────────────────────────────
    def _scatter_panel(
        panel_tag: str,
        title: str,
        ylabel: str,
        y_key: str,
        ymax: float,
        median_val: float,
        legend_pos: str = "north west",
        emit_labels: bool = False,
        suppress_xlabel: bool = False,
    ) -> None:
        w(f"%% ── Panel {panel_tag}: {title} ─────────────────────────────────────────")
        w(r"\nextgroupplot[")
        w(rf"  title={{\small ({panel_tag.lower()}) {title}}},")
        w(rf"  ylabel={{{ylabel}}},")
        w(rf"  ymax={ymax:.4g},")
        w(r"  yticklabel={\pgfmathprintnumber[fixed,precision=0]{\tick}\,s},")
        w(rf"  legend pos={legend_pos},")
        w(r"  legend columns=1,")
        if suppress_xlabel:
            w(r"  xlabel={},")
            w(r"  xticklabels={},")
        else:
            w(r"  xlabel={Number of wires},")
        w(r"]")

        for topo in active_topos:
            mark, fill, draw = TOPO_STYLE[topo]
            label = TOPO_LABEL[topo]
            pairs = [
                (r["n_wires"], r[y_key])
                for r in by_topo[topo]
                if r[y_key] > 0
            ]
            if not pairs:
                continue
            coord_str = "\n".join(f"    ({x}, {y:.2f})" for x, y in pairs)
            w(r"\addplot[")
            w(rf"  only marks, mark={mark}, mark size=1.5pt,")
            w(rf"  mark options={{fill={fill}, draw={draw}, line width=0.3pt}},")
            w(r"] coordinates {")
            w(coord_str)
            w(r"};")
            w(rf"\addlegendentry{{{label}}}")
            if emit_labels:
                w(rf"\label{{plot:topo:{topo}}}")

        # Median reference line
        w(rf"\draw[dashed, gray!70, line width=0.6pt]")
        w(rf"  (axis cs:0,{median_val:.2f}) -- (axis cs:{x_max_nice},{median_val:.2f})")
        w(rf"  node[right, font=\fontsize{{4.5}}{{5}}\selectfont, yshift=2pt]")
        w(rf"  {{med.\,{median_val:.0f}\,s}};")
        w()

    _scatter_panel(
        panel_tag="A",
        title="Board-setup execution time",
        ylabel="Duration (s)",
        y_key="board_setup_duration_s",
        ymax=_nice_linear_max(board_times),
        median_val=board_med,
        emit_labels=True,
        suppress_xlabel=True,
    )

    _scatter_panel(
        panel_tag="B",
        title="Wire-routing execution time",
        ylabel="Duration (s)",
        y_key="wire_routing_duration_s",
        ymax=_nice_linear_max(routing_times),
        median_val=routing_med,
    )

    w(r"\end{groupplot}")
    w(r"\end{tikzpicture}")

    tikz_body = "\n".join(L)
    OUTPUT_TEX.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_TEX.open("w", encoding="utf-8") as f:
        f.write(tikz_body + "\n")
    print(f"TikZ body  → {OUTPUT_TEX}")

    # ── Wrapper caption ───────────────────────────────────────────────────────
    board_max   = max(board_times)
    routing_max = max(routing_times)

    wrapper_lines = [
        r"\begin{figure}[htbp]",
        r"  \centering",
        r"  \resizebox{\columnwidth}{!}{\input{figures/execution_times.tex}}",
        (
            rf"  \caption{{Robot execution times for the BoP-to-motion-planning pipeline"
            rf" across {n_total}~synthetic harness variants"
            rf" (2--30 connectors, 2--{max(r['n_wires'] for r in rows)}~wires, four topology types)."
            " Both panels share the same x-axis (wire count) and use the same four"
            " topology markers:"
            r" \ref{plot:topo:backbone}~Backbone,"
            r" \ref{plot:topo:tree}~Tree,"
            r" \ref{plot:topo:star}~Star,"
            r" \ref{plot:topo:linear}~Linear."
            rf" Dashed lines mark the median."
            rf" \textbf{{(a)}} Board-setup execution time"
            rf" (peg and connector-holder placement motions);"
            rf" median {board_med:.0f}\,s, max {board_max:.0f}\,s."
            rf" \textbf{{(b)}} Wire-routing execution time"
            rf" (all \textsc{{route\_wire}} steps);"
            rf" median {routing_med:.0f}\,s, max {routing_max:.0f}\,s."
            rf" Per-topology parallel, single-arm, and idle fractions are reported"
            rf" in Table~\ref{{tab:harness-stats}}."
        ),
        r"  }",
        r"  \label{fig:scalability}",
        r"\end{figure}",
    ]
    wrapper = "\n".join(wrapper_lines)
    with OUTPUT_WRAPPER.open("w", encoding="utf-8") as f:
        f.write(wrapper + "\n")
    print(f"Wrapper    → {OUTPUT_WRAPPER}")

    print(f"\nKey numbers for paper:")
    print(f"  Board setup:    median={board_med:.0f}s  max={board_max:.0f}s")
    print(f"  Wire routing:   median={routing_med:.0f}s  max={routing_max:.0f}s")
    print(f"  Combined:")
    print(f"    Parallel:  median={par_med:.0f}%  max={max(par_pcts):.0f}%")
    print(f"    Single:    median={single_med:.0f}%")
    print(f"    Idle:      median={idle_med:.0f}%")

    # Per-topology parallel/single/idle table for the paper
    print(f"\nPer-topology timing breakdown (for tab:harness-stats):")
    for topo in active_topos:
        trows = by_topo[topo]
        p = _median([r["total_parallel_pct"] for r in trows])
        s = _median([r["total_single_pct"]   for r in trows])
        ii = _median([r["total_idle_pct"]     for r in trows])
        print(f"  {topo:8s}: par={p:.0f}%  single={s:.0f}%  idle={ii:.0f}%")


if __name__ == "__main__":
    main()
