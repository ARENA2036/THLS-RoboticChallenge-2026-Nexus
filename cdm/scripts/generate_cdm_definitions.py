#!/usr/bin/env python3
"""
Generate JSON Schema from Pydantic models.
Run this after modifying cdm.py, then use json-schema-to-typescript to generate cdm.ts.

Usage:
    python generate_ts.py
    npx json-schema-to-typescript cdm.schema.json -o cdm.ts

Or use the npm script:
    npm run generate:types
"""

import json
from pathlib import Path

from definitions.cdm_schema import WireHarness


def strip_titles(obj):
    """Remove title fields from JSON schema to produce cleaner TypeScript."""
    if isinstance(obj, dict):
        obj.pop('title', None)
        for v in obj.values():
            strip_titles(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_titles(item)


def main():
    script_dir = Path(__file__).parent

    schema = WireHarness.model_json_schema()
    strip_titles(schema)

    output_path = script_dir / "definitions" / "cdm.schema.json"
    with open(output_path, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"Successfully generated {output_path}")


if __name__ == "__main__":
    main()
