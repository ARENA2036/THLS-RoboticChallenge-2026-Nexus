
import json
import os
import sys
import argparse
from typing import List, Dict, Any, Union

# Add the project root to the python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from harness_builder.backend.quoting.digikey import DigiKeyClient
from public.cdm.definitions.cdm_schema import (
    WireHarness, Connector, Wire, Terminal, WireProtection, Accessory, Fixing
)

def get_unique_parts(harness: WireHarness) -> List[Union[Connector, Wire, Terminal, WireProtection, Accessory, Fixing]]:
    """Extract unique parts from the WireHarness that need enrichment."""
    parts_to_enrich = []
    seen_part_numbers = set()

    # Iterate through all component definition lists in the WireHarness
    component_lists = [
        harness.connectors,
        harness.wires,
        harness.terminals,
        harness.wire_protections,
        harness.accessories,
        harness.fixings
    ]

    for component_list in component_lists:
        for item in component_list:
            pn = item.part_number
            if not pn or pn == "Unknown":
                continue
            
            # Skip if already enriched (has manufacturer that isn't just a short code or Unknown)
            if item.manufacturer and item.manufacturer != "Unknown" and len(item.manufacturer) > 3:
                continue

            if pn not in seen_part_numbers:
                parts_to_enrich.append(item)
                seen_part_numbers.add(pn)

    return parts_to_enrich

def enrich_item(client: DigiKeyClient, item: Union[Connector, Wire, Terminal, WireProtection, Accessory, Fixing], dry_run: bool = True) -> bool:
    """Attempt to enrich a single item from DigiKey."""
    pn = item.part_number
    desc = item.description or ""
    
    print(f"  Target: {pn} ({desc})")

    if dry_run:
        print(f"  [DRY RUN] Would query DigiKey for: {pn}")
        return False

    try:
        # Step 1: Search by keyword/part number
        print(f"  Querying DigiKey for '{pn}'...")
        results = client.search_keyword(pn, limit=5)
        
        # Check for exact matches first
        exact_matches = results.get("ExactMatches", [])
        products = results.get("Products", [])
        
        target_product = None
        if exact_matches:
            target_product = exact_matches[0]
            print(f"  Found Exact Match!")
        elif products:
            # Take the first product from the general results
            target_product = products[0]
            print(f"  Found Fuzzy Match: {target_product.get('ManufacturerProductNumber')}")

        if target_product:
            # Match found, enrich the Pydantic model instance
            item.manufacturer = target_product.get("Manufacturer", {}).get("Name")
            
            # If description was missing or generic, update it
            dk_desc = target_product.get("ProductDescription")
            if dk_desc and (not item.description or item.description == "Unknown"):
                item.description = dk_desc

            # Extraction of pricing and purchase info
            item.digikey_url = target_product.get("ProductUrl")
            
            # 1. Try top-level UnitPrice first (often present in search results)
            unit_price = target_product.get("UnitPrice")
            
            # 2. If not found, look into ProductVariations -> StandardPricing
            if unit_price is None:
                variations = target_product.get("ProductVariations", [])
                for var in variations:
                    pricing = var.get("StandardPricing", [])
                    if pricing:
                        # Find the first break or the 1-unit break
                        price_info = pricing[0]
                        for p_break in pricing:
                            if p_break.get("BreakQuantity") == 1:
                                price_info = p_break
                                break
                        unit_price = price_info.get("UnitPrice")
                        # Try to get currency from price_info if available
                        if not item.currency:
                            item.currency = price_info.get("Currency")
                        if unit_price is not None:
                            break

            item.unit_price = unit_price
            if not item.currency:
                item.currency = client.currency

            print(f"  Success: {item.manufacturer} - {item.description} (Price: {item.unit_price} {item.currency})")
            return True
        else:
            print(f"  No matches found on DigiKey for {pn}")
            print("  --- Raw DigiKey Response ---")
            print(json.dumps(results, indent=2))
            print("  ----------------------------")
            return False

    except Exception as e:
        print(f"  Error during API call: {e}")
        return False

def enrich_harness(harness: WireHarness, client_kwargs: dict = None, limit: int = 100) -> WireHarness:
    """Enrich a loaded WireHarness object with DigiKey metadata."""
    parts = get_unique_parts(harness)
    if not parts:
        return harness

    client_kwargs = client_kwargs or {}
    client = DigiKeyClient(**client_kwargs)

    requests_made = 0
    for part in parts:
        if requests_made >= limit:
            break
        if enrich_item(client, part, dry_run=False):
            pass
        requests_made += 1

    return harness

def main():
    parser = argparse.ArgumentParser(description="Enrich CDM JSON with DigiKey metadata.")
    parser.add_argument("--input", required=True, help="Path to input CDM JSON file")
    parser.add_argument("--output", help="Path to output CDM JSON file (defaults to input)")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches without calling API")
    parser.add_argument("--limit", type=int, default=1, help="Max number of API requests to make (default: 1)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}")
        return

    with open(args.input, "r") as f:
        try:
            harness = WireHarness.model_validate_json(f.read())
        except Exception as e:
            print(f"Error validating CDM JSON: {e}")
            return

    if args.dry_run:
        parts = get_unique_parts(harness)
        print(f"Found {len(parts)} unique parts needing enrichment.")
        for part in parts:
            enrich_item(None, part, dry_run=True)
        print("\nDry run complete.")
    else:
        print(f"Enriching up to {args.limit} parts...")
        harness = enrich_harness(harness, limit=args.limit)
        
        output_path = args.output or args.input
        with open(output_path, "w") as f:
            f.write(harness.model_dump_json(indent=2))
        print(f"\nSaved enriched CDM to: {output_path}")

if __name__ == "__main__":
    main()

