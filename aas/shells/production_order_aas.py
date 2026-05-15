"""
ProductionOrderAAS — Business-level production order AAS.

Carries two submodels:
  1. DigitalNameplate    (IDTA 02006-2-0)
  2. ProductionOrder     (urn:NEXUS:submodel:ProductionOrder:1-0)

GlobalAssetId convention:
    urn:NEXUS:order:{order_number}
"""

from dataclasses import dataclass
from typing import List, Optional

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.production_order import build_production_order


@dataclass
class ProductionOrderAASBundle:
    """A complete ProductionOrderAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    order_submodel: model.Submodel

    def all_objects(self) -> list:
        return [self.shell, self.nameplate_submodel, self.order_submodel]


def build_production_order_aas(
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
    """Build a complete ProductionOrderAAS.

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
        ProductionOrderAASBundle with shell and two submodels.
    """
    safe_num = order_number.replace(" ", "_").replace("/", "_")
    global_asset_id = f"urn:NEXUS:order:{safe_num}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    order_id = f"{global_asset_id}/submodel/ProductionOrder"

    variants = harness_variant_asset_ids or []

    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=order_number,
        manufacturer_product_designation=(
            f"Production order {order_number}: "
            f"qty={production_quantity}, delivery={target_delivery_date}, "
            f"status={status}"
        ),
        manufacturer_product_family="ProductionOrder",
        manufacturer_product_type="WireHarnessProductionOrder",
        batch_number=order_number,
    )

    order_sm = build_production_order(
        order_id,
        order_number=order_number,
        production_quantity=production_quantity,
        target_delivery_date=target_delivery_date,
        status=status,
        harness_variant_asset_ids=variants,
        bop_asset_id=bop_asset_id,
        station_asset_id=station_asset_id,
        notes=notes,
    )

    asset_info = model.AssetInformation(
        model.AssetKind.INSTANCE,
        global_asset_id=global_asset_id,
    )

    def _sm_ref(sm: model.Submodel) -> model.ModelReference:
        return model.ModelReference(
            (model.Key(model.KeyTypes.SUBMODEL, sm.id),),
            model.Submodel,
        )

    shell = model.AssetAdministrationShell(
        asset_information=asset_info,
        id_=f"{global_asset_id}/shell",
        submodel={_sm_ref(nameplate), _sm_ref(order_sm)},
    )

    return ProductionOrderAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        order_submodel=order_sm,
    )
