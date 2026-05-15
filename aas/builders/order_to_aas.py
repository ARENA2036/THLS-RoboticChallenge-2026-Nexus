"""
Builder: Order parameters → ProductionOrderAAS.
"""

from typing import List, Optional

from ..shells.production_order_aas import (
    ProductionOrderAASBundle,
    build_production_order_aas,
)


def build_aas_from_order(
    order_number: str,
    *,
    production_quantity: int,
    target_delivery_date: str,
    status: str = "PLANNED",
    harness_variant_asset_ids: Optional[List[str]] = None,
    bop_asset_id: Optional[str] = None,
    station_asset_id: Optional[str] = None,
    notes: Optional[str] = None,
    manufacturer_name: str = "NEXUS",
) -> ProductionOrderAASBundle:
    """Build a ProductionOrderAAS from order parameters.

    Args:
        order_number: Business-level order/job number (e.g. from ERP).
        production_quantity: Number of harness units to produce.
        target_delivery_date: ISO 8601 date string (e.g. "2026-06-30").
        status: Order lifecycle state: PLANNED | IN_PRODUCTION | COMPLETED | CANCELLED.
        harness_variant_asset_ids: WireHarnessAAS GlobalAssetIds for variants in this order.
        bop_asset_id: GlobalAssetId of the linked BillOfProcessAAS.
        station_asset_id: GlobalAssetId of the target AssemblyStationAAS.
        notes: Optional free-text notes.
        manufacturer_name: Organisation placing the order.

    Returns:
        ProductionOrderAASBundle (shell + 2 submodels).
    """
    return build_production_order_aas(
        order_number,
        production_quantity=production_quantity,
        target_delivery_date=target_delivery_date,
        status=status,
        harness_variant_asset_ids=harness_variant_asset_ids,
        bop_asset_id=bop_asset_id,
        station_asset_id=station_asset_id,
        notes=notes,
        manufacturer_name=manufacturer_name,
    )
