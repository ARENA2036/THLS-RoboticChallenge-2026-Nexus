"""
IDTA 02011-1-1 — Hierarchical Structures enabling Bills of Material.

Builds a HierarchicalStructures Submodel from a CDM WireHarness.
ArcheType = "Full": complete BOM tree with all occurrences as children.

Each occurrence node carries:
  - A reference (SameAs) back to the GlobalAssetId of the corresponding ComponentAAS.
  - A human-readable label and part number as properties.

Spec: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Hierarchical%20Structures%20enabling%20Bills%20of%20Material
"""

from typing import List

import basyx.aas.model as model

from ..semantic_ids import HierarchicalBOM as SM_IDs, TechnicalProperties as Tech_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: str) -> model.Property:
    return model.Property(id_short, value_type=str, value=value)


def _occurrence_node(
    occurrence_id_short: str,
    label: str,
    part_number: str,
    component_global_asset_id: str,
    occurrence_type: str,
    quantity: int = 1,
) -> model.SubmodelElementCollection:
    """Build a BOM node SMC for one occurrence."""
    elems: list[model.SubmodelElement] = [
        model.Property(
            "OccurrenceType",
            value_type=str,
            value=occurrence_type,
        ),
        model.Property(
            "PartNumber",
            value_type=str,
            value=part_number,
            semantic_id=_sem(Tech_IDs.PART_NUMBER),
        ),
        model.Property(
            "Label",
            value_type=str,
            value=label,
        ),
        model.Property(
            "Quantity",
            value_type=int,
            value=quantity,
        ),
        # SameAs: reference to the ComponentAAS GlobalAssetId
        model.ReferenceElement(
            "SameAs",
            value=model.ExternalReference(
                (model.Key(model.KeyTypes.GLOBAL_REFERENCE, component_global_asset_id),)
            ),
            semantic_id=_sem(SM_IDs.SAME_AS),
        ),
    ]
    return model.SubmodelElementCollection(
        occurrence_id_short,
        value=elems,
        semantic_id=_sem(SM_IDs.NODE),
    )


def build_hierarchical_bom(
    submodel_id: str,
    harness,
    component_asset_ids: dict,
) -> model.Submodel:
    """Build a Hierarchical BOM submodel (IDTA 02011-1-1).

    Args:
        submodel_id: The unique AAS submodel ID.
        harness: CDM WireHarness instance.
        component_asset_ids: Dict mapping component part_number → GlobalAssetId of
            the corresponding ComponentAAS.  Used to populate SameAs references.
            Keys are formed as f"{component_type_lower}:{part_number}".

    Returns:
        A Submodel whose structure follows the IDTA 02011 BOM template.
    """

    def _caid(type_token: str, part_number: str) -> str:
        safe_pn = part_number.replace(" ", "_").replace("/", "_")
        key = f"{type_token}:{safe_pn}"
        return component_asset_ids.get(
            key, f"urn:NEXUS:component:{type_token}:{safe_pn}"
        )

    child_nodes: list[model.SubmodelElement] = []

    # --- Connector occurrences ---
    for occ in harness.connector_occurrences:
        label = occ.label or occ.id
        pn = occ.connector.part_number
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"conn_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("connector", pn),
                occurrence_type="ConnectorOccurrence",
            )
        )

    # --- Wire occurrences (simple) ---
    for occ in harness.wire_occurrences:
        pn = occ.wire.part_number
        label = occ.wire_number or occ.id
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"wire_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("wire", pn),
                occurrence_type="WireOccurrence",
            )
        )

    # --- Special wire occurrences (multi-core) ---
    for occ in harness.special_wire_occurrences:
        pn = occ.wire.part_number
        label = occ.special_wire_id or occ.id
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"specwire_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("wire", pn),
                occurrence_type="SpecialWireOccurrence",
            )
        )

    # --- Wire protection occurrences ---
    for occ in harness.wire_protection_occurrences:
        pn = occ.protection.part_number
        label = occ.label or occ.id
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"prot_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("wire_protection", pn),
                occurrence_type="WireProtectionOccurrence",
            )
        )

    # --- Accessory occurrences ---
    for occ in harness.accessory_occurrences:
        pn = occ.accessory.part_number
        label = occ.label or occ.id
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"acc_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("accessory", pn),
                occurrence_type="AccessoryOccurrence",
            )
        )

    # --- Fixing occurrences ---
    for occ in harness.fixing_occurrences:
        pn = occ.fixing.part_number
        label = occ.label or occ.id
        child_nodes.append(
            _occurrence_node(
                occurrence_id_short=f"fix_{_safe_id(occ.id)}",
                label=label,
                part_number=pn,
                component_global_asset_id=_caid("fixing", pn),
                occurrence_type="FixingOccurrence",
            )
        )

    # EntryNode: the harness itself
    entry_node_elems: list[model.SubmodelElement] = [
        model.Property(
            "HarnessId",
            value_type=str,
            value=harness.id,
        ),
        model.Property(
            "PartNumber",
            value_type=str,
            value=harness.part_number,
            semantic_id=_sem(Tech_IDs.PART_NUMBER),
        ),
        model.Property(
            "ArcheType",
            value_type=str,
            value=SM_IDs.ARCHE_TYPE_FULL,
            semantic_id=_sem(SM_IDs.ARCHE_TYPE),
        ),
    ]
    if child_nodes:
        # Children as a named collection inside EntryNode
        entry_node_elems.append(
            model.SubmodelElementCollection(
                "Children",
                value=child_nodes,
            )
        )

    entry_node = model.SubmodelElementCollection(
        "EntryNode",
        value=entry_node_elems,
        semantic_id=_sem(SM_IDs.ENTRY_NODE),
    )

    return model.Submodel(
        submodel_id,
        submodel_element=[entry_node],
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )


def _safe_id(raw: str) -> str:
    """Sanitise an arbitrary ID string for use as AAS idShort."""
    return raw.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")
