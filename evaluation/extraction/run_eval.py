#!/usr/bin/env python3
"""
Wire Harness Extraction Evaluation Framework
============================================

Usage:
    # Run on all 100 harnesses:
    python eval/run_eval.py

    # Run a subset (first 5):
    python eval/run_eval.py --range 0-4

    # Run specific cases:
    python eval/run_eval.py --cases harness_000,harness_005

    # Resume (skip already-completed cases):
    python eval/run_eval.py --resume

    # Skip enrichment (first-pass only, faster):
    python eval/run_eval.py --range 0-4 --skip-enrich

    # Custom VLM:
    python eval/run_eval.py --vlm-url http://localhost:12345

Inputs:
    data/pdfs/{stem}.pdf        wiring diagram schematics
    data/pdfs/{stem}.csv        bill of materials
    data/generated/{stem}.json  ground-truth CDM (WireHarness)

Outputs:
    eval/output/runs/{stem}/first_pass.json
    eval/output/runs/{stem}/enriched.json
    eval/output/runs/{stem}/ground_truth.json
    eval/output/runs/report.md
    eval/output/runs/report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: allow imports from repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from definitions.cdm_schema import WireHarness

from eval.config import DEFAULT_VLM_URL, DEFAULT_VLM_MODEL
from eval.render.pdf_renderer import build_cp_index
from eval.runner.pipeline_runner import EvalRunner
from eval.metrics.component_f1 import compute_connector_f1
from eval.metrics.connectivity import compute_connectivity_f1
from eval.metrics.report import CaseMetrics, write_reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_range(range_str: str) -> tuple[int, int]:
    """Parse '0-4' into (0, 4) inclusive."""
    parts = range_str.split("-")
    return int(parts[0]), int(parts[1])


def _discover_cases(
    gt_dir: Path,
    pdf_dir: Path,
    range_: tuple[int, int] | None = None,
    cases: list[str] | None = None,
) -> list[tuple[str, Path, Path, Path]]:
    """
    Return list of (stem, gt_json_path, pdf_path, csv_path) tuples.
    Filters by range or explicit case list if provided.
    """
    gt_files = sorted(gt_dir.glob("harness_*.json"))
    result = []

    for gt_path in gt_files:
        stem = gt_path.stem  # e.g. harness_042
        idx = int(stem.split("_")[1])

        # Filter by range
        if range_ is not None:
            if idx < range_[0] or idx > range_[1]:
                continue

        # Filter by explicit case list
        if cases is not None:
            if stem not in cases:
                continue

        pdf_path = pdf_dir / f"{stem}.pdf"
        csv_path = pdf_dir / f"{stem}.csv"

        if not pdf_path.exists():
            logger.warning(f"  PDF not found for {stem}, skipping")
            continue
        if not csv_path.exists():
            logger.warning(f"  CSV not found for {stem}, skipping")
            continue

        result.append((stem, gt_path, pdf_path, csv_path))

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate wire harness extraction pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--gt-dir", type=Path, default=_REPO_ROOT / "data" / "generated",
        help="Directory with ground-truth CDM JSONs (default: data/generated/).",
    )
    parser.add_argument(
        "--pdf-dir", type=Path, default=_REPO_ROOT / "data" / "pdfs",
        help="Directory with PDF+CSV inputs (default: data/pdfs/).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Root output directory (default: eval/output/).",
    )
    parser.add_argument(
        "--vlm-url", default=DEFAULT_VLM_URL,
        help=f"VLM API base URL (default: {DEFAULT_VLM_URL}).",
    )
    parser.add_argument(
        "--vlm-model", default=DEFAULT_VLM_MODEL,
        help=f"Model name to pass to the VLM API (default: {DEFAULT_VLM_MODEL}).",
    )
    parser.add_argument(
        "--range", dest="range_str", default=None,
        help="Run harness index range, e.g. '0-4' for harness_000..004.",
    )
    parser.add_argument(
        "--cases", default=None,
        help="Comma-separated case stems, e.g. 'harness_000,harness_042'.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip cases that already have first_pass.json in output.",
    )
    parser.add_argument(
        "--skip-enrich", action="store_true",
        help="Skip self-healing enrichment pass (faster).",
    )
    args = parser.parse_args()

    gt_dir: Path = args.gt_dir.resolve()
    pdf_dir: Path = args.pdf_dir.resolve()
    output_dir: Path = args.output_dir.resolve() if args.output_dir else _REPO_ROOT / "eval" / "output"
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Parse filters
    range_ = _parse_range(args.range_str) if args.range_str else None
    case_list = args.cases.split(",") if args.cases else None

    # ------------------------------------------------------------------
    # 0. Pre-flight: confirm VLM endpoint is reachable with the expected model
    # ------------------------------------------------------------------
    try:
        import requests
        resp = requests.get(f"{args.vlm_url}/v1/models", timeout=5)
        resp.raise_for_status()
        model_ids = [m.get("id") for m in resp.json().get("data", [])]
        if args.vlm_model not in model_ids:
            logger.error(
                f"VLM at {args.vlm_url} does not serve model '{args.vlm_model}'. "
                f"Available: {model_ids}"
            )
            sys.exit(1)
        logger.info(f"VLM OK: {args.vlm_url}  model={args.vlm_model}")
    except Exception as exc:
        logger.error(
            f"Cannot reach VLM at {args.vlm_url}: {exc}. "
            f"Pass --vlm-url to override."
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 1. Discover cases
    # ------------------------------------------------------------------
    cases = _discover_cases(gt_dir, pdf_dir, range_=range_, cases=case_list)
    if not cases:
        logger.error("No cases found. Check --gt-dir and --pdf-dir.")
        sys.exit(1)
    logger.info(f"Found {len(cases)} case(s) to evaluate")

    # ------------------------------------------------------------------
    # 2. Load ground truths
    # ------------------------------------------------------------------
    harnesses: list[tuple[str, Path, Path, Path, WireHarness]] = []
    for stem, gt_path, pdf_path, csv_path in cases:
        try:
            data = json.loads(gt_path.read_text())
            harness = WireHarness.model_validate(data)
            harnesses.append((stem, gt_path, pdf_path, csv_path, harness))
            logger.info(
                f"  Loaded {stem}: "
                f"{len(harness.connector_occurrences)} connectors, "
                f"{len(harness.connections)} connections"
            )
        except Exception as exc:
            logger.warning(f"  Skipping {stem}: {exc}")

    if not harnesses:
        logger.error("No valid cases could be loaded.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Run extraction + scoring
    # ------------------------------------------------------------------
    runner = EvalRunner(vlm_url=args.vlm_url, vlm_model=args.vlm_model)
    case_results: list[CaseMetrics] = []

    for stem, gt_path, pdf_path, csv_path, harness in harnesses:
        run_dir = runs_dir / stem

        # Resume: skip first-pass re-extraction if already done; run enrichment
        # on demand when --skip-enrich is not set and enriched.json is missing.
        if args.resume and (run_dir / "first_pass.json").exists():
            need_enrich = (
                not args.skip_enrich
                and not (run_dir / "enriched.json").exists()
            )
            if need_enrich:
                logger.info(f"  {stem}: first pass exists, running enrichment ...")
                result = runner.run_enrichment_only(
                    pdf_path=pdf_path,
                    csv_path=csv_path,
                    gt_path=gt_path,
                    run_dir=run_dir,
                )
            else:
                logger.info(f"  Skipping {stem} (already exists, --resume)")
                result = EvalRunner.load_result(run_dir)

            _, cp_to_cavity = build_cp_index(harness)
            fp_conn = compute_connector_f1(harness, result.first_pass)
            fp_connectivity = compute_connectivity_f1(harness, result.first_pass, cp_to_cavity)

            enr_conn = None
            enr_connectivity = None
            if result.enriched is not None:
                enr_conn = compute_connector_f1(harness, result.enriched)
                enr_connectivity = compute_connectivity_f1(harness, result.enriched, cp_to_cavity)
                
            cm = CaseMetrics(
                cdm_id=stem, n_gt_connectors=len(harness.connector_occurrences), n_gt_connections=len(harness.connections),
                fp_connector=fp_conn, fp_connectivity=fp_connectivity,
                enr_connector=enr_conn, enr_connectivity=enr_connectivity
            )
            case_results.append(cm)
            continue

        logger.info(f"  Extracting {stem} ...")

        result = runner.run_case(
            pdf_path=pdf_path,
            csv_path=csv_path,
            gt_path=gt_path,
            run_dir=run_dir,
            skip_enrich=args.skip_enrich,
        )

        # ------------------------------------------------------------------
        # 4. Compute metrics
        # ------------------------------------------------------------------
        _, cp_to_cavity = build_cp_index(harness)

        # First pass
        fp_conn = compute_connector_f1(harness, result.first_pass)
        fp_connectivity = compute_connectivity_f1(
            harness, result.first_pass, cp_to_cavity,
        )

        # Enriched
        enr_conn = None
        enr_connectivity = None
        if result.enriched is not None:
            enr_conn = compute_connector_f1(harness, result.enriched)
            enr_connectivity = compute_connectivity_f1(
                harness, result.enriched, cp_to_cavity,
            )

        cm = CaseMetrics(
            cdm_id=stem,
            n_gt_connectors=len(harness.connector_occurrences),
            n_gt_connections=len(harness.connections),
            fp_connector=fp_conn,
            fp_connectivity=fp_connectivity,
            enr_connector=enr_conn,
            enr_connectivity=enr_connectivity,
        )
        case_results.append(cm)

        enr_cf1_str = f"{enr_conn.f1:.3f}" if enr_conn else "—"
        enr_sf1_str = f"{enr_connectivity.strict_f1:.3f}" if enr_connectivity else "—"
        logger.info(
            f"  {stem}: "
            f"Connector F1 (FP/Enr) = {fp_conn.f1:.3f} / {enr_cf1_str}  |  "
            f"Connection strict F1 (FP/Enr) = {fp_connectivity.strict_f1:.3f} / {enr_sf1_str}"
        )

    # ------------------------------------------------------------------
    # 5. Write report
    # ------------------------------------------------------------------
    if not case_results:
        logger.error("No cases were evaluated. No report generated.")
        sys.exit(1)

    fp_sum = sum(c.fp_connectivity.strict_f1 for c in case_results)
    fp_mean = fp_sum / len(case_results)
    logger.info(f"Mean First Pass Matching Connectivity F1 over {len(case_results)} cases: {fp_mean:.3f}")

    enr_valid = [c for c in case_results if c.enr_connectivity is not None]
    if len(enr_valid) == len(case_results):
        enr_sum = sum(c.enr_connectivity.strict_f1 for c in enr_valid)
        enr_mean = enr_sum / len(enr_valid)
        logger.info(f"Mean Enriched Matching Connectivity F1 over {len(case_results)} cases: {enr_mean:.3f}")
        logger.info(f"Delta (Enriched - First Pass): {enr_mean - fp_mean:.3f}")

    logger.info("Writing report ...")
    md = write_reports(case_results, runs_dir)
    print("\n" + "=" * 72)
    print(md)
    print("=" * 72)
    logger.info(f"Report written to {runs_dir / 'report.md'}")


if __name__ == "__main__":
    main()
