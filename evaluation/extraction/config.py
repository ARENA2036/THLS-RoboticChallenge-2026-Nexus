"""Eval framework configuration constants."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
EVAL_DIR = REPO_ROOT / "eval"
OUTPUT_DIR = EVAL_DIR / "output"
PDFS_DIR = OUTPUT_DIR / "pdfs"
RUNS_DIR = OUTPUT_DIR / "runs"

CDM_EXAMPLES_DIR = REPO_ROOT / "public" / "cdm" / "examples"

# VLM endpoint (override via --vlm-url)
DEFAULT_VLM_URL = "http://localhost:12345"
DEFAULT_VLM_MODEL = "Qwen3.6-35B-A3B-UD-Q4_K_M"

# Fuzzy matching: minimum similarity score to accept a connector label match
LABEL_MATCH_THRESHOLD = 0.75

# PDF rendering
PDF_PAGE_WIDTH_PT = 841    # A4 landscape width
PDF_PAGE_HEIGHT_PT = 595   # A4 landscape height
PDF_SCHEMATIC_RATIO = 0.90  # top 90% for schematic
PDF_TABLE_RATIO = 0.10      # bottom 10% for wire table

# Max pins per row before wrapping to 2 rows in a connector box
CONNECTOR_MAX_PINS_SINGLE_ROW = 12

# IEC color code → WireColor enum value ("red", "blue", …)
IEC_TO_NAME: dict[str, str] = {
    "RD": "red",
    "BU": "blue",
    "GN": "green",
    "YE": "yellow",
    "BK": "black",
    "WH": "white",
    "OG": "orange",
    "BR": "brown",
    "GY": "gray",
    "VT": "unknown",
    "PK": "unknown",
    "TQ": "unknown",
    "GE": "yellow",   # German abbreviation
    "SW": "black",    # Schwarz
    "WS": "white",    # Weiss
    "RT": "red",      # Rot
    "BL": "blue",     # Blau
    "GR": "gray",     # Grau
}

# WireColor enum value → IEC code (inverse of above, canonical direction)
NAME_TO_IEC: dict[str, str] = {
    "red": "RD",
    "blue": "BU",
    "green": "GN",
    "yellow": "YE",
    "black": "BK",
    "white": "WH",
    "orange": "OG",
    "brown": "BR",
    "gray": "GY",
    "unknown": "??",
}

# reportlab RGB (0–1) for each IEC code
COLOR_MAP_RGB: dict[str, tuple[float, float, float]] = {
    "RD": (1.0, 0.0, 0.0),
    "BU": (0.0, 0.0, 1.0),
    "GN": (0.0, 0.70, 0.0),
    "YE": (1.0, 0.85, 0.0),
    "BK": (0.10, 0.10, 0.10),
    "WH": (0.85, 0.85, 0.85),
    "OG": (1.0, 0.55, 0.0),
    "VT": (0.58, 0.0, 0.83),
    "GY": (0.50, 0.50, 0.50),
    "BR": (0.55, 0.27, 0.07),
    "PK": (1.0, 0.71, 0.76),
    "TQ": (0.0, 0.78, 0.78),
    # German aliases → same colors
    "GE": (1.0, 0.85, 0.0),
    "SW": (0.10, 0.10, 0.10),
    "WS": (0.85, 0.85, 0.85),
    "RT": (1.0, 0.0, 0.0),
    "BL": (0.0, 0.0, 1.0),
    "GR": (0.50, 0.50, 0.50),
}

def get_rgb(iec_code: str) -> tuple[float, float, float]:
    """Return reportlab RGB tuple for an IEC color code. Falls back to black."""
    return COLOR_MAP_RGB.get(iec_code.upper(), (0.0, 0.0, 0.0))


def get_cover_colors(wire_occurrence) -> list:
    """
    Extract WireColor list from either a WireOccurrence or CoreOccurrence.
    Both types exist as Connection.wire_occurrence in the CDM.
    """
    # WireOccurrence: .wire.cover_colors
    wire = getattr(wire_occurrence, "wire", None)
    if wire is not None:
        return getattr(wire, "cover_colors", []) or []
    # CoreOccurrence: .core.colors
    core = getattr(wire_occurrence, "core", None)
    if core is not None:
        return getattr(core, "colors", []) or []
    return []


def get_wire_number(wire_occurrence) -> str:
    """Return wire_number from either WireOccurrence or CoreOccurrence."""
    return getattr(wire_occurrence, "wire_number", None) or ""
