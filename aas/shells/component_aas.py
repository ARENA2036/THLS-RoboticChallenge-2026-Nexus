"""
ComponentAAS — Tier-2 supplier AAS for individual CDM component definitions.

One shell per unique CDM component (Connector, Wire, Terminal, WireProtection,
Accessory, Fixing).  Each shell carries two submodels:
  1. DigitalNameplate  (IDTA 02006-2-0)
  2. TechnicalProperties (urn:NEXUS:submodel:TechnicalProperties:1-0)

GlobalAssetId convention:
    urn:NEXUS:component:{component_type_lower}:{part_number}
"""

from dataclasses import dataclass
from typing import Set

import basyx.aas.model as model

from ..submodels.digital_nameplate import build_digital_nameplate
from ..submodels.technical_properties import build_technical_properties


# Mapping from CDM class name to a short type token used in IDs
_COMPONENT_TYPE_TOKEN = {
    "Connector": "connector",
    "Wire": "wire",
    "Terminal": "terminal",
    "WireProtection": "wire_protection",
    "Accessory": "accessory",
    "Fixing": "fixing",
}

# Human-readable product family names
_PRODUCT_FAMILY = {
    "Connector": "ConnectorHousing",
    "Wire": "Wire",
    "Terminal": "CrimpTerminal",
    "WireProtection": "WireProtection",
    "Accessory": "Accessory",
    "Fixing": "CableFixing",
}


@dataclass
class ComponentAASBundle:
    """A complete ComponentAAS: shell + its submodels."""
    shell: model.AssetAdministrationShell
    nameplate_submodel: model.Submodel
    technical_properties_submodel: model.Submodel

    def all_objects(self) -> list:
        """Return all identifiable AAS objects for insertion into an ObjectStore."""
        return [self.shell, self.nameplate_submodel, self.technical_properties_submodel]


def build_component_aas(component) -> ComponentAASBundle:
    """Build a complete ComponentAAS from any CDM component definition.

    Args:
        component: CDM component instance (Connector, Wire, Terminal, etc.)

    Returns:
        ComponentAASBundle with shell and two submodels.
    """
    class_name = type(component).__name__
    type_token = _COMPONENT_TYPE_TOKEN.get(class_name, class_name.lower())
    product_family = _PRODUCT_FAMILY.get(class_name, class_name)

    # Sanitise part number for use in URNs (replace spaces/slashes)
    safe_pn = component.part_number.replace(" ", "_").replace("/", "_")

    global_asset_id = f"urn:NEXUS:component:{type_token}:{safe_pn}"
    nameplate_id = f"{global_asset_id}/submodel/DigitalNameplate"
    tech_props_id = f"{global_asset_id}/submodel/TechnicalProperties"

    # --- DigitalNameplate ---
    nameplate = build_digital_nameplate(
        nameplate_id,
        manufacturer_name=getattr(component, "manufacturer", None),
        manufacturer_part_number=component.part_number,
        manufacturer_product_designation=getattr(component, "description", None),
        manufacturer_product_family=product_family,
        manufacturer_product_type=class_name,
    )

    # --- TechnicalProperties ---
    tech_props = build_technical_properties(tech_props_id, component)

    # --- Shell ---
    asset_info = model.AssetInformation(
        model.AssetKind.TYPE,  # component definitions are type-level assets
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
        submodel={_sm_ref(nameplate), _sm_ref(tech_props)},
    )

    return ComponentAASBundle(
        shell=shell,
        nameplate_submodel=nameplate,
        technical_properties_submodel=tech_props,
    )
