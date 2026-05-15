"""
Board setup simulation -- CDM-driven peg and connector-holder placement.

Thin CLI wrapper that delegates to BoardSetupRunner.

Usage:
    python -m simulation.examples.run_board_setup \
        --cdm-file public/cdm/examples/simple_harness.json \
        --viewer --keep-open
"""

from __future__ import annotations

import argparse
import os

from simulation.examples.board_setup.BoardSetupRunner import runBoardSetup

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None  # type: ignore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Board setup simulation: CDM-driven peg and holder placement.",
    )
    parser.add_argument(
        "--cdm-file", type=str, required=True,
        help="Path to CDM wire harness JSON file.",
    )
    parser.add_argument("--viewer", action="store_true", help="Launch MuJoCo viewer.")
    parser.add_argument("--force-viewer", action="store_true", help="Bypass viewer checks.")
    parser.add_argument("--keep-open", action="store_true", help="Keep viewer open after execution.")
    parser.add_argument(
        "--reactive",
        action="store_true",
        help="Run step-by-step reactive execution with live orientation updates.",
    )
    args = parser.parse_args()

    if mujoco is None:
        raise RuntimeError("MuJoCo is not installed.")

    result = runBoardSetup(
        cdm_file=args.cdm_file,
        use_viewer=args.viewer,
        force_viewer=args.force_viewer,
        keep_open=args.keep_open,
        use_reactive=args.reactive,
    )

    os._exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
