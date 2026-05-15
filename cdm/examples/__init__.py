"""
Example CDM harnesses for testing and demonstration.

This module provides pre-built wire harness CDM examples of varying complexity.
"""

import json
from pathlib import Path

from public.cdm.definitions.cdm_schema import WireHarness


EXAMPLES_DIR = Path(__file__).parent


def load_example(name: str) -> WireHarness:
    """
    Load an example harness by name.

    Uses the layout-extended models to ensure all fields are available.

    Args:
        name: Example name ('simple', 'medium', or 'complex')

    Returns:
        WireHarness instance with layout-extended ConnectorOccurrence

    Raises:
        FileNotFoundError: If example doesn't exist
    """
    # Import here to avoid circular imports
    from layout_generator.LayoutModels import (
        ConnectorOccurrence as LayoutConnectorOccurrence,
    )

    filepath = EXAMPLES_DIR / f"{name}_harness.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Example '{name}' not found at {filepath}")

    with open(filepath, "r") as file:
        data = json.load(file)

    # Load base harness
    harness = WireHarness.model_validate(data)

    # Convert connector occurrences to layout-extended version
    if "connector_occurrences" in data and data["connector_occurrences"]:
        extended_occurrences = []
        for occ_data in data["connector_occurrences"]:
            extended_occ = LayoutConnectorOccurrence.model_validate(occ_data)
            extended_occurrences.append(extended_occ)
        harness.connector_occurrences = extended_occurrences

    return harness


def list_examples() -> list[str]:
    """List available example names."""
    return ["simple", "medium", "complex"]


def get_example_path(name: str) -> Path:
    """Get the file path for an example."""
    return EXAMPLES_DIR / f"{name}_harness.json"
