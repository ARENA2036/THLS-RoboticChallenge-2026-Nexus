"""
Builder: WireHarness → PreFabBillOfProcessAAS.
"""

from ..shells.prefab_bop_aas import (
    PreFabBoPAASBundle,
    build_prefab_bop_aas,
)


def build_aas_from_prefab(
    harness,
    strip_length_mm: float = 8.0,
    default_crimp_force_n: float = 500.0,
    manufacturer_name: str = "NEXUS",
) -> PreFabBoPAASBundle:
    """Build a PreFabBillOfProcessAAS from a WireHarness.

    Generates Cut → Strip → Crimp process steps following OPC 40570.

    Args:
        harness: WireHarness CDM instance.
        strip_length_mm: Default insulation strip length in mm.
        default_crimp_force_n: Default crimp force in Newtons.
        manufacturer_name: Organisation performing pre-fabrication.

    Returns:
        PreFabBoPAASBundle (shell + 2 submodels).
    """
    return build_prefab_bop_aas(
        harness,
        strip_length_mm=strip_length_mm,
        default_crimp_force_n=default_crimp_force_n,
        manufacturer_name=manufacturer_name,
    )
