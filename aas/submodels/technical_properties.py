"""
Custom submodel: TechnicalProperties (urn:NEXUS:submodel:TechnicalProperties:1-0).

Encodes the type-specific mechanical and electrical properties of each CDM
component class: Connector, Wire, Terminal, WireProtection, Accessory, Fixing.
One submodel per component instance (i.e., per unique part number).
"""

from typing import List, Optional

import basyx.aas.model as model

from ..semantic_ids import TechnicalProperties as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _str_prop(id_short: str, value: Optional[str], sem_iri: str) -> Optional[model.Property]:
    if value is None:
        return None
    return model.Property(id_short, value_type=str, value=value, semantic_id=_sem(sem_iri))


def _float_prop(
    id_short: str, value: Optional[float], sem_iri: str
) -> Optional[model.Property]:
    if value is None:
        return None
    return model.Property(id_short, value_type=float, value=value, semantic_id=_sem(sem_iri))


def _collect(id_short: str, elems: list, sem_iri: str) -> Optional[model.SubmodelElementCollection]:
    present = [e for e in elems if e is not None]
    if not present:
        return None
    return model.SubmodelElementCollection(id_short, value=present, semantic_id=_sem(sem_iri))


# ---------------------------------------------------------------------------
# CDM import — done here to avoid circular deps in builders
# ---------------------------------------------------------------------------
def _build_connector_properties(connector) -> list:
    """Build properties for a CDM Connector."""
    from public.cdm.definitions.cdm_schema import Connector  # noqa: F401

    elems = [
        _str_prop("ConnectorType", connector.connector_type, SM_IDs.CONNECTOR_TYPE),
        _str_prop("HousingColor", connector.housing_color, SM_IDs.HOUSING_COLOR),
        _str_prop("HousingCode", connector.housing_code, SM_IDs.HOUSING_CODE),
        _str_prop("Material", connector.material, SM_IDs.MATERIAL),
        _float_prop("MassG", connector.mass_g, SM_IDs.MASS_G),
        _float_prop("UnitPrice", connector.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", connector.currency, SM_IDs.CURRENCY),
    ]

    # Slots → SubmodelElementList of SubmodelElementCollections
    slot_smcs = []
    for i, slot in enumerate(connector.slots or []):
        cavity_smcs = []
        for j, cavity in enumerate(slot.cavities or []):
            cav_elems = [
                model.Property("CavityId", value_type=str, value=cavity.id),
                model.Property("CavityNumber", value_type=str, value=cavity.cavity_number),
                model.Property(
                    "IsAvailable", value_type=bool, value=cavity.is_available
                ),
                model.Property(
                    "HasIntegratedTerminal",
                    value_type=bool,
                    value=cavity.has_integrated_terminal,
                ),
            ]
            cavity_smcs.append(
                model.SubmodelElementCollection(None, value=cav_elems)
            )
        slot_props: list[model.SubmodelElement] = [
            model.Property("SlotId", value_type=str, value=slot.id),
            model.Property("SlotNumber", value_type=str, value=slot.slot_number),
            model.Property("NumCavities", value_type=int, value=slot.num_cavities),
            model.Property("Gender", value_type=str, value=slot.gender),
        ]
        if cavity_smcs:
            slot_props.append(
                model.SubmodelElementList(
                    "Cavities",
                    type_value_list_element=model.SubmodelElementCollection,
                    value=cavity_smcs,
                )
            )
        slot_smcs.append(model.SubmodelElementCollection(None, value=slot_props))

    if slot_smcs:
        elems.append(
            model.SubmodelElementList(
                "Slots",
                type_value_list_element=model.SubmodelElementCollection,
                value=slot_smcs,
            )
        )

    return elems


def _build_wire_properties(wire) -> list:
    """Build properties for a CDM Wire."""
    elems = [
        _str_prop("WireType", wire.wire_type, SM_IDs.WIRE_TYPE),
        _float_prop("CrossSectionMm2", wire.cross_section_area_mm2, SM_IDs.CROSS_SECTION_MM2),
        _float_prop("OutsideDiameterMm", wire.outside_diameter, SM_IDs.OUTSIDE_DIAMETER_MM),
        _str_prop("ConductorMaterial", wire.material_conductor, SM_IDs.CONDUCTOR_MATERIAL),
        _str_prop("InsulationMaterial", wire.material_insulation, SM_IDs.INSULATION_MATERIAL),
        _str_prop("Material", wire.material_conductor, SM_IDs.MATERIAL),
        _float_prop("MassG", wire.mass_g, SM_IDs.MASS_G),
        _float_prop("UnitPrice", wire.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", wire.currency, SM_IDs.CURRENCY),
    ]

    # Cover colors as a list of string properties
    color_props = [
        model.Property(None, value_type=str, value=f"{c.color_type}:{c.color_code}")
        for c in (wire.cover_colors or [])
    ]
    if color_props:
        elems.append(
            model.SubmodelElementList(
                "CoverColors",
                type_value_list_element=model.Property,
                value_type_list_element=str,
                value=color_props,
            )
        )

    # Cores for multi-core cables
    core_smcs = []
    for core in wire.cores or []:
        core_elems = [
            model.Property("CoreId", value_type=str, value=core.id),
            model.Property("WireType", value_type=str, value=core.wire_type or ""),
        ]
        if core.cross_section_area_mm2 is not None:
            core_elems.append(
                model.Property("CrossSectionMm2", value_type=float, value=core.cross_section_area_mm2)
            )
        if core.outside_diameter_mm is not None:
            core_elems.append(
                model.Property("OutsideDiameterMm", value_type=float, value=core.outside_diameter_mm)
            )
        core_color_props = [
            model.Property(None, value_type=str, value=f"{c.color_type}:{c.color_code}")
            for c in (core.colors or [])
        ]
        if core_color_props:
            core_elems.append(
                model.SubmodelElementList(
                    "Colors",
                    type_value_list_element=model.Property,
                    value_type_list_element=str,
                    value=core_color_props,
                )
            )
        core_smcs.append(model.SubmodelElementCollection(None, value=core_elems))

    if core_smcs:
        elems.append(
            model.SubmodelElementList(
                "Cores",
                type_value_list_element=model.SubmodelElementCollection,
                value=core_smcs,
            )
        )

    return elems


def _build_terminal_properties(terminal) -> list:
    return [
        _str_prop("TerminalType", terminal.terminal_type, SM_IDs.TERMINAL_TYPE),
        _str_prop("Gender", terminal.gender, SM_IDs.GENDER),
        _float_prop("MinCrossSectionMm2", terminal.min_cross_section_mm, SM_IDs.MIN_CROSS_SECTION_MM2),
        _float_prop("MaxCrossSectionMm2", terminal.max_cross_section_mm, SM_IDs.MAX_CROSS_SECTION_MM2),
        _float_prop("UnitPrice", terminal.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", terminal.currency, SM_IDs.CURRENCY),
    ]


def _build_wire_protection_properties(wp) -> list:
    return [
        _str_prop("ProtectionType", wp.protection_type, SM_IDs.PROTECTION_TYPE),
        _str_prop("Material", wp.material, SM_IDs.MATERIAL),
        _float_prop("MassG", wp.mass_g, SM_IDs.MASS_G),
        _float_prop("UnitPrice", wp.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", wp.currency, SM_IDs.CURRENCY),
    ]


def _build_accessory_properties(acc) -> list:
    return [
        _str_prop("AccessoryType", acc.accessory_type, SM_IDs.ACCESSORY_TYPE),
        _str_prop("Material", acc.material, SM_IDs.MATERIAL),
        _float_prop("MassG", acc.mass_g, SM_IDs.MASS_G),
        _float_prop("UnitPrice", acc.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", acc.currency, SM_IDs.CURRENCY),
    ]


def _build_fixing_properties(fixing) -> list:
    return [
        _str_prop("FixingType", fixing.fixing_type, SM_IDs.FIXING_TYPE),
        _str_prop("Material", fixing.material, SM_IDs.MATERIAL),
        _float_prop("MassG", fixing.mass_g, SM_IDs.MASS_G),
        _float_prop("UnitPrice", fixing.unit_price, SM_IDs.UNIT_PRICE),
        _str_prop("Currency", fixing.currency, SM_IDs.CURRENCY),
    ]


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_technical_properties(submodel_id: str, component) -> model.Submodel:
    """Build a TechnicalProperties submodel for any CDM component definition.

    Dispatches on the component's class name to pick the right property builder.

    Args:
        submodel_id: The unique AAS submodel ID.
        component: Any CDM component instance (Connector, Wire, Terminal, etc.)

    Returns:
        A Submodel with type-specific technical properties.
    """
    class_name = type(component).__name__

    dispatch = {
        "Connector": _build_connector_properties,
        "Wire": _build_wire_properties,
        "Terminal": _build_terminal_properties,
        "WireProtection": _build_wire_protection_properties,
        "Accessory": _build_accessory_properties,
        "Fixing": _build_fixing_properties,
    }

    builder_fn = dispatch.get(class_name)
    if builder_fn is None:
        raise ValueError(f"No TechnicalProperties builder for component type: {class_name}")

    raw_elements = builder_fn(component)
    elements = [e for e in raw_elements if e is not None]

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
