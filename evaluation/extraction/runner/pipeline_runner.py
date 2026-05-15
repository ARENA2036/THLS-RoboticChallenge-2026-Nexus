"""
Eval pipeline runner.

Wraps WiringDiagramExtractor (extract_wiring_diagram.py) to run two modes:
  - FirstPassExtractor: Phases 1+2 only (connectors + wires, no self-healing)
  - Full pipeline:      Phases 1+2+3 (includes _heal_missing_references)

Both modes save their WiringDiagram output to JSON and return the object.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Resolve project paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from parsing.extract_wiring_diagram import WiringDiagramExtractor
from parsing.util.structure import WiringDiagram


# ---------------------------------------------------------------------------
# First-pass-only subclass
# ---------------------------------------------------------------------------

class FirstPassExtractor(WiringDiagramExtractor):
    """
    Runs Phases 1+2 only (connector + wire extraction).
    Skips Phase 3 (_heal_missing_references) entirely.
    """

    def __init__(self, *args, **kwargs):
        """Truncate vlm_turns.jsonl before the VLMClient can log to it.

        First-pass is the head of a run, so any prior conversation log in
        this run_dir is stale (from a previous attempt). We wipe it here;
        later phases (healing / enrichment) append to the fresh file.
        """
        log_dir = kwargs.get("log_dir")
        if log_dir:
            jl = Path(log_dir) / "vlm_turns.jsonl"
            if jl.exists():
                jl.unlink()
        super().__init__(*args, **kwargs)

    def extract(self) -> Optional[WiringDiagram]:
        """Override: stop after wire extraction, skip self-healing."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("FirstPassExtractor: running Phases 1+2 only (no self-healing)")

        if not self.page_images:
            logger.error("No images available from PDF")
            return None

        # Phase 0: primer (image + BOM).
        self._prime_conversation()

        # Phase 1
        logger.info("Phase 1: Extracting connectors (single-pass)...")
        self._extract_connectors_single_pass()
        logger.info(f"  Extracted {len(self.accumulated_connectors)} connectors")

        # Phase 2
        logger.info("Phase 2: Extracting wires (single-pass)...")
        self._extract_wires_single_pass()
        logger.info(f"  Extracted {len(self.accumulated_wires)} wires")

        # Assemble (Phase 4 — no Phase 3 healing)
        logger.info("Assembling WiringDiagram (first-pass only)...")
        diagram = self._assemble_diagram()
        self._save_output(diagram)

        logger.info(
            f"First-pass extraction complete: "
            f"{len(diagram.connectors)} connectors, {len(diagram.wires)} wires"
        )
        return diagram


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    run_dir: Path
    first_pass: Optional[WiringDiagram]
    enriched: Optional[WiringDiagram]

    def first_pass_path(self) -> Path:
        return self.run_dir / "first_pass.json"

    def enriched_path(self) -> Path:
        return self.run_dir / "enriched.json"

    def ground_truth_path(self) -> Path:
        return self.run_dir / "ground_truth.json"


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

class EvalRunner:
    """
    Runs both first-pass and full-pipeline extraction for a given PDF,
    saves outputs to run_dir, and returns a RunResult.
    """

    def __init__(self, vlm_url: str = "http://localhost:12345", vlm_model: str = "default"):
        self.vlm_url = vlm_url
        self.vlm_model = vlm_model

    def run_case(
        self,
        pdf_path: Path,
        csv_path: Path,
        gt_path: Path,
        run_dir: Path,
        skip_enrich: bool = False,
    ) -> RunResult:
        """
        Args:
            pdf_path:     Path to the wiring diagram PDF.
            csv_path:     Path to the BOM CSV.
            gt_path:      Path to the ground-truth CDM JSON.
            run_dir:      Directory to write first_pass.json / enriched.json.
            skip_enrich:  If True, only run first-pass; enriched will be None.

        Returns:
            RunResult with loaded WiringDiagram objects and paths.
        """
        run_dir.mkdir(parents=True, exist_ok=True)

        fp_out = str(run_dir / "first_pass.json")
        full_out = str(run_dir / "enriched.json")

        # ── First pass only ──────────────────────────────────────────────
        fp_diagram: Optional[WiringDiagram] = None
        try:
            fp_extractor = FirstPassExtractor(
                pdf_path=str(pdf_path),
                csv_path=str(csv_path),
                output_path=fp_out,
                vlm_url=self.vlm_url,
                vlm_model=self.vlm_model,
                log_dir=str(run_dir),
            )
            fp_diagram = fp_extractor.extract()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                f"First-pass extraction failed for {pdf_path.name}: {exc}"
            )

        # ── Enrichment: rehydrate from first-pass, then self-heal ────────
        #
        # Instead of running a second independent extraction, we continue
        # the same conversation: load connectors + wires from first_pass.json
        # and the VLM conversation from vlm_turns.jsonl, then run only the
        # healing phase.  This guarantees the enriched output starts from
        # the exact same first-pass data (no VLM non-determinism).
        enriched_diagram: Optional[WiringDiagram] = None
        if not skip_enrich and fp_diagram is not None:
            try:
                enrich_extractor = WiringDiagramExtractor(
                    pdf_path=str(pdf_path),
                    csv_path=str(csv_path),
                    output_path=full_out,
                    vlm_url=self.vlm_url,
                    vlm_model=self.vlm_model,
                    log_dir=str(run_dir),
                )
                enriched_diagram = enrich_extractor.enrich_from_first_pass(run_dir)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    f"Enrichment failed for {pdf_path.name}: {exc}"
                )

        # ── Copy ground truth ────────────────────────────────────────────
        shutil.copy(gt_path, run_dir / "ground_truth.json")

        return RunResult(
            run_dir=run_dir,
            first_pass=fp_diagram,
            enriched=enriched_diagram,
        )

    def run_enrichment_only(
        self,
        pdf_path: Path,
        csv_path: Path,
        gt_path: Path,
        run_dir: Path,
    ) -> RunResult:
        """Run only the enrichment (healing) phase on an existing first pass.

        Rehydrates the extractor's VLM conversation + accumulated state
        from run_dir/first_pass.json and run_dir/vlm_turns.jsonl, then
        runs _heal_missing_references on top of that conversation.
        Writes enriched.json; leaves first_pass.json untouched.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        full_out = str(run_dir / "enriched.json")

        enriched_diagram: Optional[WiringDiagram] = None
        try:
            extractor = WiringDiagramExtractor(
                pdf_path=str(pdf_path),
                csv_path=str(csv_path),
                output_path=full_out,
                vlm_url=self.vlm_url,
                vlm_model=self.vlm_model,
                log_dir=str(run_dir),
            )
            enriched_diagram = extractor.enrich_from_first_pass(run_dir)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                f"Enrichment failed for {pdf_path.name}: {exc}"
            )

        shutil.copy(gt_path, run_dir / "ground_truth.json")

        fp_diagram = EvalRunner.load_wiring_diagram(run_dir / "first_pass.json")
        return RunResult(
            run_dir=run_dir,
            first_pass=fp_diagram,
            enriched=enriched_diagram,
        )

    # ------------------------------------------------------------------
    # Static helpers: load saved results back from disk
    # ------------------------------------------------------------------

    @staticmethod
    def load_wiring_diagram(path: Path) -> Optional[WiringDiagram]:
        """Load a WiringDiagram from a JSON file saved by the extractor."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return WiringDiagram.model_validate(data)
        except Exception:
            return None

    @staticmethod
    def load_result(run_dir: Path) -> RunResult:
        """Reconstruct a RunResult from a previously saved run directory."""
        fp = EvalRunner.load_wiring_diagram(run_dir / "first_pass.json")
        en = EvalRunner.load_wiring_diagram(run_dir / "enriched.json")
        return RunResult(run_dir=run_dir, first_pass=fp, enriched=en)
