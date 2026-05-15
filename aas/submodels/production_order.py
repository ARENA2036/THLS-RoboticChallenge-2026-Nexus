"""
Custom submodel: ProductionOrder (urn:NEXUS:submodel:ProductionOrder:1-0).

Represents the business-level production order that triggers the pipeline
(Section 3, Gap 3 of the paper — "SPoT" trigger):
  - OrderNumber, ProductionQuantity, TargetDeliveryDate, Status
  - HarnessVariants: references to WireHarnessAAS GlobalAssetIds
  - LinkedBillOfProcess: reference to BillOfProcessAAS GlobalAssetId
  - LinkedStation: reference to AssemblyStationAAS GlobalAssetId

This submodel bridges the ERP/MES layer with the robot assembly pipeline.
"""

from typing import List, Optional

import basyx.aas.model as model

from ..semantic_ids import ProductionOrder as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _int_prop(id_short: str, value: int) -> model.Property:
    return model.Property(id_short, value_type=int, value=value)


def _asset_ref(global_asset_id: str) -> model.ExternalReference:
    """Create an ExternalReference pointing to a GlobalAssetId."""
    return model.ExternalReference(
        (model.Key(model.KeyTypes.GLOBAL_REFERENCE, global_asset_id),)
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_production_order(
    submodel_id: str,
    *,
    order_number: str,
    production_quantity: int,
    target_delivery_date: str,
    status: str = "PLANNED",
    harness_variant_asset_ids: Optional[List[str]] = None,
    bop_asset_id: Optional[str] = None,
    station_asset_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> model.Submodel:
    """Build a ProductionOrder submodel.

    Args:
        submodel_id: Unique AAS submodel ID.
        order_number: Business-level order/job number (e.g. from ERP).
        production_quantity: Number of harness units to produce.
        target_delivery_date: ISO 8601 date string (e.g. "2026-06-30").
        status: Order lifecycle state: PLANNED | IN_PRODUCTION | COMPLETED | CANCELLED.
        harness_variant_asset_ids: List of WireHarnessAAS GlobalAssetIds ordered.
        bop_asset_id: GlobalAssetId of the linked BillOfProcessAAS.
        station_asset_id: GlobalAssetId of the target AssemblyStationAAS.
        notes: Optional free-text notes from the order.

    Returns:
        Populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    # Core order properties
    elements.append(
        model.Property("OrderNumber", value_type=str, value=order_number,
                       semantic_id=_sem(SM_IDs.ORDER_NUMBER))
    )
    elements.append(
        model.Property("ProductionQuantity", value_type=int, value=production_quantity,
                       semantic_id=_sem(SM_IDs.PRODUCTION_QUANTITY))
    )
    elements.append(
        model.Property("TargetDeliveryDate", value_type=str, value=target_delivery_date,
                       semantic_id=_sem(SM_IDs.TARGET_DELIVERY_DATE))
    )
    elements.append(
        model.Property("Status", value_type=str, value=status,
                       semantic_id=_sem(SM_IDs.STATUS))
    )

    if notes:
        elements.append(_str_prop("Notes", notes))

    # Harness variant references — each as a ReferenceElement in a SML
    variants = harness_variant_asset_ids or []
    variant_refs = model.SubmodelElementList(
        "HarnessVariants",
        type_value_list_element=model.ReferenceElement,
        value=[
            model.ReferenceElement(None, value=_asset_ref(aid))
            for aid in variants
        ],
        semantic_id=_sem(SM_IDs.HARNESS_VARIANT_REF),
    )
    elements.append(variant_refs)

    # Optional linked AAS references
    if bop_asset_id:
        elements.append(
            model.ReferenceElement(
                "LinkedBillOfProcess",
                value=_asset_ref(bop_asset_id),
                semantic_id=_sem(SM_IDs.BOP_REF),
            )
        )

    if station_asset_id:
        elements.append(
            model.ReferenceElement(
                "LinkedStation",
                value=_asset_ref(station_asset_id),
                semantic_id=_sem(SM_IDs.STATION_REF),
            )
        )

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
