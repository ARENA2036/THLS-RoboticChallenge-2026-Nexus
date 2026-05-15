"""
Configuration for the BoP Generator.

Defines station configuration and harness-to-station assignments
required as input to the BoPGeneratorService.
"""

import sys
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

# Add parent directory to path for CDM / layout imports
_parent_dir = Path(__file__).resolve().parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

from layout_generator.LayoutModels import LayoutResponse
from public.cdm.definitions.cdm_schema import WireHarness


class HarnessInput(BaseModel):
    """Input bundle for a single harness: CDM + layout result + station assignment."""
    harness: WireHarness
    layout_response: LayoutResponse
    station_id: str
    cdm_source: Optional[str] = None
    layout_source: Optional[str] = None


class BoPGeneratorConfig(BaseModel):
    """Configuration for the BoP generator.

    Attributes:
        production_id: Unique identifier for this production batch.
        harness_inputs: List of harness inputs (CDM + layout + station assignment).
    """
    production_id: str
    harness_inputs: List[HarnessInput] = Field(min_length=1)
