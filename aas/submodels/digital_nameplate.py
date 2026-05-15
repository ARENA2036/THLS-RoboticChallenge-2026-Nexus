"""
IDTA 02006-2-0 — Digital Nameplate for Industrial Equipment.

Builds a Digital Nameplate Submodel from a flat set of string values.
Used by all four AAS types (WireHarness, AssemblyStation, BillOfProcess, Component).

Spec: https://github.com/admin-shell-io/submodel-templates/tree/main/published/Digital%20Nameplate
"""

from typing import Optional

import basyx.aas.model as model

from ..semantic_ids import DigitalNameplate as SM_IDs


def _sem(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def _prop(id_short: str, value: Optional[str], sem_iri: str) -> Optional[model.Property]:
    """Return a string Property, or None if value is absent."""
    if value is None:
        return None
    return model.Property(
        id_short,
        value_type=str,
        value=value,
        semantic_id=_sem(sem_iri),
    )


def _mlprop(
    id_short: str, value: Optional[str], sem_iri: str, lang: str = "en"
) -> Optional[model.MultiLanguageProperty]:
    """Return a MultiLanguageProperty (single language), or None if value is absent."""
    if value is None:
        return None
    return model.MultiLanguageProperty(
        id_short,
        value={lang: value},
        semantic_id=_sem(sem_iri),
    )


def build_digital_nameplate(
    submodel_id: str,
    *,
    manufacturer_name: Optional[str] = None,
    manufacturer_product_designation: Optional[str] = None,
    manufacturer_part_number: Optional[str] = None,
    manufacturer_product_family: Optional[str] = None,
    manufacturer_product_type: Optional[str] = None,
    serial_number: Optional[str] = None,
    batch_number: Optional[str] = None,
    hardware_version: Optional[str] = None,
    software_version: Optional[str] = None,
    year_of_construction: Optional[str] = None,
    date_of_manufacture: Optional[str] = None,
    uri_of_the_product: Optional[str] = None,
) -> model.Submodel:
    """Build a Digital Nameplate submodel (IDTA 02006-2-0).

    Args:
        submodel_id: The unique AAS submodel ID (IRI or URN).
        All remaining kwargs map directly to IDTA 02006 properties.
        None values are omitted from the submodel.

    Returns:
        A fully populated Submodel ready for serialization.
    """
    elements: list[model.SubmodelElement] = []

    mappings = [
        ("ManufacturerName", manufacturer_name, SM_IDs.MANUFACTURER_NAME),
        (
            "ManufacturerProductDesignation",
            manufacturer_product_designation,
            SM_IDs.MANUFACTURER_PRODUCT_DESIGNATION,
        ),
        ("ManufacturerPartNumber", manufacturer_part_number, SM_IDs.MANUFACTURER_PART_NUMBER),
        (
            "ManufacturerProductFamily",
            manufacturer_product_family,
            SM_IDs.MANUFACTURER_PRODUCT_FAMILY,
        ),
        ("ManufacturerProductType", manufacturer_product_type, SM_IDs.MANUFACTURER_PRODUCT_TYPE),
        ("SerialNumber", serial_number, SM_IDs.SERIAL_NUMBER),
        ("BatchNumber", batch_number, SM_IDs.BATCH_NUMBER),
        ("HardwareVersion", hardware_version, SM_IDs.HARDWARE_VERSION),
        ("SoftwareVersion", software_version, SM_IDs.SOFTWARE_VERSION),
        ("YearOfConstruction", year_of_construction, SM_IDs.YEAR_OF_CONSTRUCTION),
        ("DateOfManufacture", date_of_manufacture, SM_IDs.DATE_OF_MANUFACTURE),
        ("URIOfTheProduct", uri_of_the_product, SM_IDs.URI_OF_THE_PRODUCT),
    ]

    for id_short, value, sem_iri in mappings:
        if value is None:
            continue
        elem = _prop(id_short, value, sem_iri)
        if elem is not None:
            elements.append(elem)

    return model.Submodel(
        submodel_id,
        submodel_element=elements,
        semantic_id=_sem(SM_IDs.SUBMODEL),
    )
